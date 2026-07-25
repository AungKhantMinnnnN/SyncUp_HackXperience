"""Scheduling service (Member A). Owns the confirm transaction — the heart of the app.

Import direction: scheduling MAY import resources + finance. They must never import us.
The only layer that writes to the DB.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time import overlaps
from app.core.types import BudgetDraft, EventView, ReservationPlan
from app.features.finance import service as finance_service
from app.features.resources import service as resources_service
from app.features.scheduling import agent
from app.features.scheduling.scoring import (
    BusyInterval,
    Constraints as ScoringConstraints,
    Interval,
    MemberView,
    score_slots,
)
from app.models.org import Member, Organization
from app.models.scheduling import (
    BusyBlock,
    Event,
    EventAttendee,
    SchedulingRequest,
    SlotProposal,
)

_LEADERSHIP = {"president", "exec", "treasurer"}
_GROUP_KEYWORDS = ("exec", "board", "lead", "officer", "president")


def _required_ids(members: list[Member], group: str | None) -> set[UUID]:
    """Which members must attend. A leadership-flavored group narrows to officers;
    otherwise everyone is required (so weighted attendance spans the whole org)."""
    if group and any(k in group.lower() for k in _GROUP_KEYWORDS):
        officers = {m.id for m in members if m.role in _LEADERSHIP}
        if officers:
            return officers
    return {m.id for m in members}


async def _fairness(db: AsyncSession, org_id: UUID) -> dict[UUID, int]:
    """member_id -> times they missed one of the org's last 5 completed events.
    Empty until events have RSVP history, so the penalty is a no-op on fresh data."""
    recent = list(
        (
            await db.execute(
                select(Event.id)
                .where(Event.org_id == org_id, Event.status == "completed")
                .order_by(Event.start_utc.desc())
                .limit(5)
            )
        ).scalars()
    )
    if not recent:
        return {}
    missed = (
        await db.execute(
            select(EventAttendee.member_id).where(
                EventAttendee.event_id.in_(recent),
                EventAttendee.rsvp_status.in_(("declined", "no_show")),
            )
        )
    ).scalars()
    return dict(Counter(missed))


async def create_request(
    db: AsyncSession, prompt: str, member_id: UUID | None = None
) -> tuple[UUID, str]:
    """Parse -> score -> persist top-5 proposals. Returns (request_id, status).
    Scheduling's own entry point, so it owns this transaction and commits."""
    org_id = settings.org_id
    req = SchedulingRequest(
        org_id=org_id, created_by=member_id, raw_prompt=prompt, status="parsing"
    )
    db.add(req)
    await db.flush()

    try:
        constraints = await agent.parse_intent(prompt, db=db, org_id=org_id)
    except Exception:  # noqa: BLE001 — unparseable after retries is a terminal state
        req.status = "failed"
        await db.commit()
        return req.id, req.status

    req.parsed_constraints = constraints.model_dump(mode="json")
    req.status = "proposing"

    members = list((await db.execute(select(Member).where(Member.org_id == org_id))).scalars())
    required = _required_ids(members, constraints.attendee_group)
    member_views = [
        MemberView(id=m.id, weight=m.priority_weight, required=m.id in required) for m in members
    ]

    member_ids = [m.id for m in members]
    busy_rows = (
        await db.execute(
            select(BusyBlock).where(
                BusyBlock.member_id.in_(member_ids),
                BusyBlock.end_utc > constraints.window_start,
                BusyBlock.start_utc < constraints.window_end,
            )
        )
    ).scalars()
    busy = [
        BusyInterval(member_id=b.member_id, kind=b.kind, start=b.start_utc, end=b.end_utc)
        for b in busy_rows
    ]

    org = await db.get(Organization, org_id)
    quiet = (
        (org.quiet_hours_start, org.quiet_hours_end)
        if org and org.quiet_hours_start is not None and org.quiet_hours_end is not None
        else None
    )
    existing = [
        Interval(start=e.start_utc, end=e.end_utc)
        for e in (
            await db.execute(
                select(Event).where(
                    Event.org_id == org_id,
                    Event.status.in_(("confirmed", "draft")),
                    Event.end_utc > constraints.window_start,
                    Event.start_utc < constraints.window_end,
                )
            )
        ).scalars()
    ]

    slots = score_slots(
        ScoringConstraints(
            duration_minutes=constraints.duration_minutes,
            window_start=constraints.window_start,
            window_end=constraints.window_end,
            must_be_before=constraints.must_be_before,
        ),
        member_views,
        busy,
        existing_events=existing,
        fairness=await _fairness(db, org_id),
        quiet_hours=quiet,
        tz=org.timezone if org else None,
    )

    name_by_id = {m.id: m.full_name for m in members}
    for rank, s in enumerate(slots, start=1):
        db.add(
            SlotProposal(
                request_id=req.id,
                start_utc=s.start,
                end_utc=s.end,
                score=Decimal(str(s.score)),
                attendance_pct=Decimal(str(s.attendance_pct)),
                conflicts={
                    "reasons": s.conflicts,
                    "free": [name_by_id.get(mid, str(mid)) for mid in s.free_member_ids],
                },
                rank=rank,
            )
        )

    req.status = "awaiting_choice"
    await db.commit()
    return req.id, req.status


async def availability(
    db: AsyncSession, frm: datetime, to: datetime
) -> tuple[int, list[tuple[datetime, int]]]:
    """Heatmap data (doc §7): free member count per 1-hour bucket across [frm, to).
    Returns (member_count, [(hour_start_utc, free_count), ...]).
    ponytail: naive O(hours * members * blocks) scan — fine for a 12-member org over a
    few weeks; push the overlap into SQL (a gist range join) only if it ever drags."""
    org_id = settings.org_id
    member_ids = list(
        (await db.execute(select(Member.id).where(Member.org_id == org_id))).scalars()
    )
    block_rows = (
        await db.execute(
            select(BusyBlock).where(
                BusyBlock.member_id.in_(member_ids),
                BusyBlock.end_utc > frm,
                BusyBlock.start_utc < to,
            )
        )
    ).scalars()
    by_member: dict[UUID, list[tuple[datetime, datetime]]] = {}
    for b in block_rows:
        by_member.setdefault(b.member_id, []).append((b.start_utc, b.end_utc))

    cells: list[tuple[datetime, int]] = []
    hour = frm.replace(minute=0, second=0, microsecond=0)
    while hour < to:
        h_end = hour + timedelta(hours=1)
        free = sum(
            1
            for mid in member_ids
            if not any(overlaps(hour, h_end, s, e) for s, e in by_member.get(mid, ()))
        )
        cells.append((hour, free))
        hour = h_end
    return len(member_ids), cells


async def list_events(db: AsyncSession, frm: datetime, to: datetime) -> list[Event]:
    rows = await db.execute(
        select(Event)
        .where(Event.org_id == settings.org_id, Event.end_utc > frm, Event.start_utc < to)
        .order_by(Event.start_utc)
    )
    return list(rows.scalars())


async def event_details(db: AsyncSession, event_id: UUID):
    """Attendee names + allocated packing-list items for one event. Packing items come
    from resources (scheduling MAY import resources; never the reverse)."""
    members = list(
        (
            await db.execute(
                select(Member.full_name)
                .join(EventAttendee, EventAttendee.member_id == Member.id)
                .where(EventAttendee.event_id == event_id)
                .order_by(Member.full_name)
            )
        ).scalars()
    )
    items = await resources_service.list_packing_list_items(db, event_id)
    return members, items


async def get_org(db: AsyncSession) -> Organization | None:
    return await db.get(Organization, settings.org_id)


async def list_members(db: AsyncSession) -> list[Member]:
    return list(
        (
            await db.execute(
                select(Member).where(Member.org_id == settings.org_id).order_by(Member.full_name)
            )
        ).scalars()
    )


# A member claimed by two overlapping events is the same conflict as a double-booked
# resource — the one interval-overlap primitive, applied to people.
_MEMBER_CONFLICT_QUERY = text(
    """
    SELECT m.id AS member_id, m.full_name AS member,
           e1.id AS event_a_id, e1.title AS event_a,
           e2.id AS event_b_id, e2.title AS event_b
    FROM event_attendees a1
    JOIN event_attendees a2 ON a2.member_id = a1.member_id AND a1.event_id < a2.event_id
    JOIN events e1 ON e1.id = a1.event_id
    JOIN events e2 ON e2.id = a2.event_id
    JOIN members m ON m.id = a1.member_id
    WHERE e1.org_id = :o AND e2.org_id = :o
      AND e1.status IN ('confirmed', 'draft') AND e2.status IN ('confirmed', 'draft')
      AND e1.start_utc < e2.end_utc AND e2.start_utc < e1.end_utc
    ORDER BY e1.title, e2.title, m.full_name
    """
)


async def list_member_conflicts(db: AsyncSession) -> list[dict]:
    """Members double-booked across two overlapping (confirmed/draft) events."""
    rows = await db.execute(_MEMBER_CONFLICT_QUERY, {"o": settings.org_id})
    return [dict(r) for r in rows.mappings().all()]


async def remove_attendees(db: AsyncSession, event_id: UUID, member_ids: list[UUID]) -> int:
    """Drop members from an event — the one-click resolution for a double-booking.
    Commits its own transaction (standalone action, nothing wraps it)."""
    result = await db.execute(
        delete(EventAttendee).where(
            EventAttendee.event_id == event_id, EventAttendee.member_id.in_(member_ids)
        )
    )
    await db.commit()
    return result.rowcount or 0


async def reschedule_event(db: AsyncSession, event_id: UUID) -> Event | None:
    """Move an event to a new day to clear a double-booking, keeping every attendee.
    Keeps the same time of day and walks forward to the first future day where none of
    the attendees are committed to another event, preferring days with the fewest
    personal (busy_block) clashes. Saves the new date to `events` and commits. Returns
    None if no clear day exists in the horizon."""
    event = await db.get(Event, event_id)
    if event is None:
        return None
    duration = event.end_utc - event.start_utc

    attendee_ids = list(
        (
            await db.execute(
                select(EventAttendee.member_id).where(EventAttendee.event_id == event_id)
            )
        ).scalars()
    )
    if not attendee_ids:
        return None

    now = now_utc()
    horizon = now + timedelta(days=28)
    busy = [
        (b.start_utc, b.end_utc)
        for b in (
            await db.execute(
                select(BusyBlock).where(
                    BusyBlock.member_id.in_(attendee_ids),
                    BusyBlock.end_utc > now,
                    BusyBlock.start_utc < horizon,
                )
            )
        ).scalars()
    ]
    # Other events these attendees are on — the slots the reschedule must avoid.
    other = [
        (r.start_utc, r.end_utc)
        for r in (
            await db.execute(
                select(Event.start_utc, Event.end_utc)
                .join(EventAttendee, EventAttendee.event_id == Event.id)
                .where(
                    EventAttendee.member_id.in_(attendee_ids),
                    Event.id != event_id,
                    Event.end_utc > now,
                    Event.start_utc < horizon,
                    Event.status.in_(("confirmed", "draft", "rescheduled")),
                )
            )
        ).all()
    ]

    best: tuple[datetime, datetime, int] | None = None
    for day in range(1, 29):  # tomorrow .. 4 weeks out, same time of day
        start = event.start_utc + timedelta(days=day)
        end = start + duration
        if start <= now:
            continue
        if any(overlaps(start, end, o_start, o_end) for o_start, o_end in other):
            continue  # would just re-create a double-booking
        clashes = sum(1 for b_start, b_end in busy if overlaps(start, end, b_start, b_end))
        if best is None or clashes < best[2]:
            best = (start, end, clashes)
            if clashes == 0:
                break  # a perfectly free day — take it

    if best is None:
        return None
    event.start_utc, event.end_utc = best[0], best[1]
    event.status = "rescheduled"
    await db.commit()
    await db.refresh(event)
    return event


async def calendar(
    db: AsyncSession, frm: datetime, to: datetime
) -> tuple[list[Member], list[BusyBlock], list]:
    """Members, their busy blocks, and the events they attend in [frm, to) — powers the
    per-member month calendar."""
    members = list(
        (
            await db.execute(
                select(Member).where(Member.org_id == settings.org_id).order_by(Member.full_name)
            )
        ).scalars()
    )
    ids = [m.id for m in members]
    blocks = list(
        (
            await db.execute(
                select(BusyBlock).where(
                    BusyBlock.member_id.in_(ids),
                    BusyBlock.end_utc > frm,
                    BusyBlock.start_utc < to,
                )
            )
        ).scalars()
    )
    events = list(
        (
            await db.execute(
                select(
                    EventAttendee.member_id, Event.title, Event.start_utc, Event.end_utc
                )
                .join(Event, Event.id == EventAttendee.event_id)
                .where(
                    Event.org_id == settings.org_id,
                    Event.end_utc > frm,
                    Event.start_utc < to,
                    Event.status.in_(("confirmed", "draft", "rescheduled")),
                )
            )
        ).all()
    )
    return members, blocks, events


async def get_request(db: AsyncSession, request_id: UUID) -> SchedulingRequest | None:
    return await db.get(SchedulingRequest, request_id)


async def get_proposals(db: AsyncSession, request_id: UUID) -> list[SlotProposal]:
    rows = await db.execute(
        select(SlotProposal)
        .where(SlotProposal.request_id == request_id)
        .order_by(SlotProposal.rank)
    )
    return list(rows.scalars())


class AlreadyConfirmed(Exception):
    """Raised when confirming a proposal that already has an event (router -> 409)."""


@dataclass
class EventPlan:
    event: Event
    reservations: ReservationPlan
    budget: BudgetDraft


async def _load_proposal(db: AsyncSession, proposal_id: UUID) -> SlotProposal:
    proposal = await db.get(SlotProposal, proposal_id)
    if proposal is None:
        raise LookupError(proposal_id)
    return proposal


async def _create_event(
    db: AsyncSession, proposal: SlotProposal, request: SchedulingRequest, actor_id: UUID | None
) -> Event:
    event = Event(
        org_id=request.org_id,
        created_by=actor_id,
        title=(request.raw_prompt or "Event").strip()[:120],
        start_utc=proposal.start_utc,
        end_utc=proposal.end_utc,
        status="confirmed",
    )
    db.add(event)
    await db.flush()  # assign event.id
    proposal.selected = True
    proposal.event_id = event.id
    return event


async def _add_attendees(db: AsyncSession, event: Event) -> None:
    members = (await db.execute(select(Member).where(Member.org_id == event.org_id))).scalars()
    for m in members:
        db.add(EventAttendee(event_id=event.id, member_id=m.id, required=False))


async def confirm_proposal(
    db: AsyncSession, proposal_id: UUID, actor_id: UUID | None = None
) -> EventPlan:
    """One transaction across all three modules (doc §6). Create the event, hold the
    resources, draft the budget — all on one session. Any exception (including the
    resources btree_gist exclusion) rolls back the whole plan."""
    async with db.begin():  # BEGIN
        proposal = await _load_proposal(db, proposal_id)
        if proposal.event_id is not None:  # already confirmed — don't create a second event
            raise AlreadyConfirmed(proposal.event_id)
        request = await db.get(SchedulingRequest, proposal.request_id)
        event = await _create_event(db, proposal, request, actor_id)
        await _add_attendees(db, event)

        # Direct in-process calls. Same session, same transaction. Not HTTP, not a queue.
        ev = EventView(
            id=event.id,
            org_id=event.org_id,
            title=event.title,
            start_utc=event.start_utc,
            end_utc=event.end_utc,
            venue_id=event.venue_id,
        )
        reservations = await resources_service.plan_for_event(db, ev)
        budget = await finance_service.draft_for_event(db, ev, reservations)
    # COMMIT here.
    return EventPlan(event=event, reservations=reservations, budget=budget)
