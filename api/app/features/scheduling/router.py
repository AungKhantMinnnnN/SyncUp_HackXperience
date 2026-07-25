"""Scheduling routes (doc §7). Routes only — parse, call service, return.
Mounted under /api/scheduling in app/main.py."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.features.scheduling import agent, service
from app.features.scheduling.schemas import (
    AvailabilityCell,
    AvailabilityOut,
    BudgetOut,
    BusyOut,
    CalendarOut,
    EventAllocation,
    EventBusyOut,
    MemberConflictOut,
    MemberOut,
    RecommendIn,
    RecommendOut,
    RemoveAttendeesIn,
    ConfirmIn,
    CreateRequestIn,
    CreateRequestOut,
    EventListItem,
    EventOut,
    EventPlanOut,
    OrgOut,
    ProposalOut,
    RequestStatusOut,
    ReservationsOut,
)
from app.models.scheduling import SlotProposal

router = APIRouter()


def _plan_to_out(plan: service.EventPlan) -> EventPlanOut:
    r, b, e = plan.reservations, plan.budget, plan.event
    return EventPlanOut(
        event=EventOut(
            id=e.id, title=e.title, start_utc=e.start_utc, end_utc=e.end_utc, status=e.status
        ),
        reservations=ReservationsOut(
            reservation_ids=r.reservation_ids,
            unowned_items=[
                {"item_name": u.item_name, "quantity": u.quantity, "est_cost": str(u.est_cost)}
                for u in r.unowned_items
            ],
            venue_cost=str(r.venue_cost),
        ),
        budget=BudgetOut(
            event_budget_id=b.event_budget_id,
            estimated_total=str(b.estimated_total),
            stated_cap=str(b.stated_cap) if b.stated_cap is not None else None,
            verdict=b.verdict,
        ),
    )


def _to_out(p: SlotProposal) -> ProposalOut:
    conf = p.conflicts if isinstance(p.conflicts, dict) else {}
    return ProposalOut(
        id=p.id,
        start_utc=p.start_utc,
        end_utc=p.end_utc,
        score=float(p.score) if p.score is not None else None,
        attendance_pct=float(p.attendance_pct) if p.attendance_pct is not None else None,
        rank=p.rank,
        conflicts=conf.get("reasons", []),
        available_members=conf.get("free", []),
    )


@router.get("/org", response_model=OrgOut)
async def get_org(db: AsyncSession = Depends(get_db)):
    org = await service.get_org(db)
    if org is None:
        raise HTTPException(404, detail={"detail": "Org not found", "code": "not_found"})
    return OrgOut(id=org.id, name=org.name, timezone=org.timezone)


@router.get("/members", response_model=list[MemberOut])
async def get_members(db: AsyncSession = Depends(get_db)):
    return [
        MemberOut(id=m.id, full_name=m.full_name, role=m.role)
        for m in await service.list_members(db)
    ]


@router.get("/member-conflicts", response_model=list[MemberConflictOut])
async def get_member_conflicts(db: AsyncSession = Depends(get_db)):
    rows = await service.list_member_conflicts(db)
    return [MemberConflictOut(**r) for r in rows]


@router.post("/events/{event_id}/remove-attendees")
async def remove_attendees(
    event_id: UUID, body: RemoveAttendeesIn, db: AsyncSession = Depends(get_db)
) -> dict:
    removed = await service.remove_attendees(db, event_id, body.member_ids)
    return {"removed": removed}


@router.post("/member-conflicts/recommend", response_model=RecommendOut)
async def recommend_resolution(body: RecommendIn) -> RecommendOut:
    text = await agent.recommend_member_resolution(body.event_a, body.event_b, body.members)
    return RecommendOut(recommendation=text)


@router.post("/events/{event_id}/reschedule", response_model=EventListItem)
async def reschedule_event(event_id: UUID, db: AsyncSession = Depends(get_db)):
    event = await service.reschedule_event(db, event_id)
    if event is None:
        raise HTTPException(
            409, detail={"detail": "No conflict-free day found to move it to", "code": "no_slot"}
        )
    members, items = await service.event_details(db, event.id)
    return EventListItem(
        id=event.id,
        title=event.title,
        start_utc=event.start_utc,
        end_utc=event.end_utc,
        status=event.status,
        venue_id=event.venue_id,
        members=members,
        items=[
            EventAllocation(item_name=i.item_name, quantity=i.quantity, org_owned=i.org_owned)
            for i in items
        ],
    )


@router.get("/calendar", response_model=CalendarOut)
async def get_calendar(
    frm: datetime = Query(alias="from"),
    to: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
):
    members, blocks, events = await service.calendar(db, frm, to)
    return CalendarOut(
        members=[MemberOut(id=m.id, full_name=m.full_name, role=m.role) for m in members],
        busy=[
            BusyOut(member_id=b.member_id, kind=b.kind, start_utc=b.start_utc, end_utc=b.end_utc)
            for b in blocks
        ],
        events=[
            EventBusyOut(
                member_id=r.member_id, title=r.title, start_utc=r.start_utc, end_utc=r.end_utc
            )
            for r in events
        ],
    )


@router.post("/requests", response_model=CreateRequestOut)
async def create_request(body: CreateRequestIn, db: AsyncSession = Depends(get_db)):
    request_id, status = await service.create_request(db, body.prompt, body.member_id)
    return CreateRequestOut(request_id=request_id, status=status)


@router.get("/requests/{request_id}", response_model=RequestStatusOut)
async def get_request(request_id: UUID, db: AsyncSession = Depends(get_db)):
    req = await service.get_request(db, request_id)
    if req is None:
        raise HTTPException(404, detail={"detail": "Request not found", "code": "not_found"})
    proposals = await service.get_proposals(db, request_id)
    return RequestStatusOut(
        request_id=req.id,
        status=req.status,
        parsed_constraints=req.parsed_constraints,
        proposals=[_to_out(p) for p in proposals],
    )


@router.get("/requests/{request_id}/proposals", response_model=list[ProposalOut])
async def get_proposals(request_id: UUID, db: AsyncSession = Depends(get_db)):
    return [_to_out(p) for p in await service.get_proposals(db, request_id)]


@router.post("/proposals/{proposal_id}/confirm", response_model=EventPlanOut)
async def confirm(
    proposal_id: UUID, body: ConfirmIn | None = None, db: AsyncSession = Depends(get_db)
):
    try:
        plan = await service.confirm_proposal(db, proposal_id, body.actor_id if body else None)
    except LookupError:
        raise HTTPException(404, detail={"detail": "Proposal not found", "code": "not_found"})
    except service.AlreadyConfirmed:
        raise HTTPException(409, detail={"detail": "Proposal already confirmed", "code": "conflict"})
    return _plan_to_out(plan)


@router.get("/availability", response_model=AvailabilityOut)
async def get_availability(
    frm: datetime = Query(alias="from"),
    to: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
):
    member_count, cells = await service.availability(db, frm, to)
    return AvailabilityOut(
        member_count=member_count,
        cells=[
            AvailabilityCell(day=h.date().isoformat(), hour=h.hour, free_count=free)
            for h, free in cells
        ],
    )


@router.get("/events", response_model=list[EventListItem])
async def get_events(
    frm: datetime = Query(alias="from"),
    to: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
):
    out = []
    for e in await service.list_events(db, frm, to):
        members, items = await service.event_details(db, e.id)
        out.append(
            EventListItem(
                id=e.id,
                title=e.title,
                start_utc=e.start_utc,
                end_utc=e.end_utc,
                status=e.status,
                venue_id=e.venue_id,
                members=members,
                items=[
                    EventAllocation(item_name=i.item_name, quantity=i.quantity, org_owned=i.org_owned)
                    for i in items
                ],
            )
        )
    return out
