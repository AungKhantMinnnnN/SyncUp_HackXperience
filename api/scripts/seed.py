"""One-shot demo seed for ALL three modules — run once, demo everything.

Deterministic (fixed per-member RNG) and idempotent (TRUNCATE ... CASCADE then insert),
so re-running resets to the exact same state. Single org, pinned to settings.org_id.

Populates:
  scheduling  — 1 org, 10 members, 4 venues, ~130 busy_blocks (SGT daytime, 3 weeks),
                5 past completed events (with RSVPs incl. repeat no-shows -> fairness
                debt), and 2 overlapping upcoming events for the resource conflict demo.
  resources   — ~15 catalogue items; reservations that make "Film Screening" hold the
                projector while "Orientation Night" (same window) is blocked; packing
                lists for Orientation Night (owned + unowned items).
  finance     — a semester budget, per-event budgets (one over cap), itemized line
                items, and a couple of expenses. Written via raw SQL because finance's
                ORM models don't exist yet (Member C) — the tables do (schema.sql).

Run:  python scripts/seed.py   (against the DEV Supabase project only)
"""

import asyncio
import random
from datetime import time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.core.time import now_utc
from app.db import SessionLocal
from app.models.org import Member, Organization, Venue
from app.models.resources import PackingListItem, Resource, ResourceReservation
from app.models.scheduling import BusyBlock, Event, EventAttendee

ORG_NAME = "Chess Club"
ORG_TZ = "Asia/Singapore"
LOCAL = ZoneInfo(ORG_TZ)  # times below are org-local; TIMESTAMPTZ stores them as UTC
SEMESTER = "Fall 2026"

# (full_name, role, priority_weight) — weights per scoring ref (doc §4)
MEMBERS = [
    ("Ava Chen", "president", 3),
    ("Ben Ortiz", "treasurer", 2),
    ("Cara Idris", "exec", 2),
    ("Dan Whitfield", "exec", 2),
    ("Elif Kaya", "member", 1),
    ("Frank Novak", "member", 1),
    ("Grace Liu", "member", 1),
    ("Hugo Marsh", "member", 1),
    ("Ivy Sanders", "member", 1),
    ("Jae Park", "member", 1),
]

# (name, capacity, hourly_cost)
VENUES = [
    ("Student Union Room 200", 120, "0"),
    ("Library Seminar A", 25, "15.00"),
    ("Auditorium B", 300, "50.00"),
    ("Quad Lawn", 500, "0"),
]

# (name, category, quantity_total, exclusive) — ~15 items per doc §6/§11
RESOURCES = [
    ("Projector", "AV", 1, True),
    ("Wireless mic", "AV", 4, False),
    ("Portable speaker", "AV", 2, False),
    ("HDMI cable", "AV", 6, False),
    ("Folding chair", "furniture", 120, False),
    ("Folding table", "furniture", 20, False),
    ("Sign-in table", "furniture", 2, False),
    ("Whiteboard", "furniture", 3, False),
    ("Event banner", "signage", 3, False),
    ("Table cloth", "signage", 10, False),
    ("Extension cord", "electrical", 8, False),
    ("Power strip", "electrical", 6, False),
    ("First-aid kit", "safety", 2, False),
    ("Cash box", "admin", 1, True),
    ("Name-tag pack", "admin", 5, False),
]

BUSY_KINDS = ["class", "class", "class", "work", "club", "personal"]


def _week_monday_local():
    """Midnight org-local (SGT) on Monday of the current week."""
    t = now_utc().astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)
    return t - timedelta(days=t.weekday())


def _build_busy_blocks(members) -> list[BusyBlock]:
    base = _week_monday_local()
    blocks: list[BusyBlock] = []
    for m in members:
        rng = random.Random(m.full_name)  # deterministic per member
        weekdays = rng.sample(range(5), 4)
        start_hour = rng.choice([9, 10, 11, 13, 14, 15, 16])  # SGT daytime
        for wd in weekdays:
            kind = rng.choice(BUSY_KINDS)
            dur = rng.choice([60, 75, 90])
            for week in range(3):
                s = base + timedelta(days=wd + 7 * week, hours=start_hour)
                blocks.append(
                    BusyBlock(
                        member_id=m.id, kind=kind, start_utc=s,
                        end_utc=s + timedelta(minutes=dur), weight=1, source="seed",
                    )
                )
        exam_day = rng.choice(range(5))
        es = base + timedelta(days=exam_day + 14, hours=rng.choice([9, 13, 15]))
        blocks.append(
            BusyBlock(
                member_id=m.id, kind="exam", start_utc=es,
                end_utc=es + timedelta(minutes=120), weight=3, source="seed",
            )
        )
    return blocks


def _demo_conflicts(members) -> list[BusyBlock]:
    """Deterministic, explainable member conflicts so /plan visibly steers around them
    on stage (the random blocks above make the calendar realistic but aren't nameable):

      * The exec board (treasurer + both execs) works Wed 14:00-18:00 SGT next week and
        the week after — a SOFT conflict, so an exec meeting there scores low on
        attendance and gets out-ranked.
      * The president has an exam next-week Tuesday 10:00-12:00 — a HARD conflict
        (kind='exam'), so any overlapping slot is eliminated outright.

    Demo line: "the AI knows the board works Wednesday afternoons and the president has a
    Tuesday exam, so it proposes a time when everyone's actually free."
    """
    base = _week_monday_local()
    blocks: list[BusyBlock] = []
    for m in members[1:4]:  # Ben (treasurer), Cara & Dan (execs)
        for week in (1, 2):
            s = base + timedelta(days=2 + 7 * week, hours=14)  # Wednesday 14:00 SGT
            blocks.append(
                BusyBlock(member_id=m.id, kind="work", start_utc=s,
                          end_utc=s + timedelta(hours=4), weight=1, source="seed-demo")
            )
    exam = base + timedelta(days=1 + 7, hours=10)  # next-week Tuesday 10:00 SGT
    blocks.append(
        BusyBlock(member_id=members[0].id, kind="exam", start_utc=exam,  # Ava (president)
                  end_utc=exam + timedelta(hours=2), weight=3, source="seed-demo")
    )
    return blocks


def _build_past_events(org, roster, venue):
    """5 past completed events with RSVPs. The last two members are repeat no-shows so
    fairness debt (>=2 of last 5) fires in scheduling's scorer."""
    base = _week_monday_local()
    events: list[Event] = []
    rsvps: list[tuple[Event, Member, str]] = []
    no_show_ids = {m.id for m in roster[-2:]}
    for k in range(5):
        s = base - timedelta(weeks=5 - k) + timedelta(days=2, hours=18)  # Wed 18:00 SGT
        ev = Event(
            org_id=org.id, created_by=roster[0].id, venue_id=venue.id,
            title=f"{org.name} weekly meeting #{k + 1}",
            start_utc=s, end_utc=s + timedelta(hours=1),
            expected_attendance=len(roster), status="completed",
        )
        events.append(ev)
        for m in roster:
            missed = m.id in no_show_ids and k < 3
            rsvps.append((ev, m, "no_show" if missed else "attended"))
    return events, rsvps


async def _seed_finance(
    db, org_id: UUID, event_a: Event, event_b: Event, treasurer_id: UUID
) -> None:
    """Raw SQL — finance ORM models don't exist yet (Member C); the tables do."""
    budget_id = uuid4()
    await db.execute(
        text(
            "INSERT INTO budgets (id, org_id, semester, total_allocated, currency) "
            "VALUES (:id, :org_id, :semester, :total, 'USD')"
        ),
        {"id": budget_id, "org_id": org_id, "semester": SEMESTER, "total": Decimal("5000.00")},
    )

    # Film Screening — comfortably within cap. Orientation Night — over cap (demo).
    eb_a, eb_b = uuid4(), uuid4()
    await db.execute(
        text(
            "INSERT INTO event_budgets "
            "(id, event_id, budget_id, estimated_total, actual_total, stated_cap, status) "
            "VALUES (:id, :event_id, :budget_id, :est, :actual, :cap, :status)"
        ),
        {"id": eb_a, "event_id": event_a.id, "budget_id": budget_id,
         "est": Decimal("300.00"), "actual": Decimal("250.00"),
         "cap": Decimal("400.00"), "status": "approved"},
    )
    await db.execute(
        text(
            "INSERT INTO event_budgets "
            "(id, event_id, budget_id, estimated_total, actual_total, stated_cap, status) "
            "VALUES (:id, :event_id, :budget_id, :est, :actual, :cap, :status)"
        ),
        {"id": eb_b, "event_id": event_b.id, "budget_id": budget_id,
         "est": Decimal("1200.00"), "actual": Decimal("640.00"),
         "cap": Decimal("1000.00"), "status": "approved"},  # est > cap => over_cap verdict
    )

    # (event_budget_id, category, description, unit_cost, quantity)
    line_items = [
        (eb_a, "food", "Snacks & drinks", "3.00", 50),
        (eb_a, "materials", "Film licence", "150.00", 1),
        (eb_b, "food", "Catering platter", "120.00", 5),
        (eb_b, "venue", "Auditorium B hire", "50.00", 4),
        (eb_b, "equipment_rental", "Backup projector rental", "150.00", 1),
        (eb_b, "printing", "Flyers & name tags", "0.20", 200),
        (eb_b, "contingency", "Buffer", "110.00", 1),
    ]
    first_food_line = None
    for eb_id, category, desc, unit, qty in line_items:
        li_id = uuid4()
        if eb_id == eb_b and category == "food":
            first_food_line = li_id
        await db.execute(
            text(
                "INSERT INTO budget_line_items "
                "(id, event_budget_id, category, description, unit_cost, quantity, line_total, source) "
                "VALUES (:id, :eb, :cat, :desc, :unit, :qty, :total, 'ai')"
            ),
            {"id": li_id, "eb": eb_id, "cat": category, "desc": desc,
             "unit": Decimal(unit), "qty": qty, "total": Decimal(unit) * qty},
        )

    spent = now_utc() - timedelta(days=2)
    await db.execute(
        text(
            "INSERT INTO expenses "
            "(id, event_budget_id, line_item_id, paid_by, amount, description, status, spent_at) "
            "VALUES (:id, :eb, :li, :paid_by, :amt, :desc, :status, :spent)"
        ),
        {"id": uuid4(), "eb": eb_b, "li": first_food_line, "paid_by": treasurer_id,
         "amt": Decimal("600.00"), "desc": "Catering deposit", "status": "approved", "spent": spent},
    )
    await db.execute(
        text(
            "INSERT INTO expenses "
            "(id, event_budget_id, line_item_id, paid_by, amount, description, status, spent_at) "
            "VALUES (:id, :eb, NULL, :paid_by, :amt, :desc, :status, :spent)"
        ),
        {"id": uuid4(), "eb": eb_b, "paid_by": treasurer_id,
         "amt": Decimal("40.00"), "desc": "Printing (pending)", "status": "pending", "spent": spent},
    )


async def seed() -> None:
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(text("TRUNCATE organizations CASCADE"))

            org = Organization(
                id=settings.org_id, name=ORG_NAME, timezone=ORG_TZ,
                quiet_hours_start=time(22, 0), quiet_hours_end=time(8, 0),
            )
            db.add(org)
            await db.flush()

            members = [
                Member(org_id=org.id, full_name=fn, role=role, priority_weight=w)
                for fn, role, w in MEMBERS
            ]
            venues = [
                Venue(org_id=org.id, name=nm, capacity=cap, hourly_cost=Decimal(cost))
                for nm, cap, cost in VENUES
            ]
            db.add_all(members)
            db.add_all(venues)
            await db.flush()

            db.add_all(_build_busy_blocks(members))
            db.add_all(_demo_conflicts(members))  # deterministic member conflicts for /plan

            past_events, rsvps = _build_past_events(org, members, venues[0])

            # Two overlapping upcoming events — the resource conflict demo. Film Screening
            # holds the (exclusive) projector; Orientation Night wants it in the same
            # window and is therefore blocked -> "two competing events" (doc §10).
            demo_start = now_utc() + timedelta(days=1)
            demo_end = demo_start + timedelta(hours=3)
            film = Event(
                org_id=org.id, created_by=members[2].id, venue_id=venues[2].id,
                title="AV Club Film Screening", start_utc=demo_start, end_utc=demo_end,
                expected_attendance=80, status="confirmed",
            )
            orientation = Event(
                org_id=org.id, created_by=members[0].id, venue_id=venues[0].id,
                title="Freshman Orientation Night", start_utc=demo_start, end_utc=demo_end,
                expected_attendance=100, status="confirmed",
            )
            db.add_all([*past_events, film, orientation])
            await db.flush()

            db.add_all(
                EventAttendee(
                    event_id=ev.id, member_id=m.id,
                    required=(m.role != "member"), rsvp_status=status,
                )
                for ev, m, status in rsvps
            )
            # Attendees for the two upcoming demo events.
            db.add_all(
                EventAttendee(event_id=orientation.id, member_id=m.id,
                              required=(m.role != "member"), rsvp_status="attending")
                for m in members
            )
            db.add_all(
                EventAttendee(event_id=film.id, member_id=m.id,
                              required=(m.role != "member"), rsvp_status="attending")
                for m in members[:5]
            )

            resources = {
                name: Resource(org_id=org.id, name=name, category=cat, quantity_total=qty, exclusive=excl)
                for name, cat, qty, excl in RESOURCES
            }
            db.add_all(resources.values())
            await db.flush()

            # Film Screening holds the projector + 3 mics for the window; Orientation
            # Night holds 100 chairs but NOT the projector (blocked).
            db.add_all([
                ResourceReservation(
                    resource_id=resources["Projector"].id, event_id=film.id, quantity=1,
                    start_utc=demo_start, end_utc=demo_end, exclusive=True, status="confirmed",
                ),
                ResourceReservation(
                    resource_id=resources["Wireless mic"].id, event_id=film.id, quantity=3,
                    start_utc=demo_start, end_utc=demo_end, exclusive=False, status="held",
                ),
                ResourceReservation(
                    resource_id=resources["Folding chair"].id, event_id=orientation.id, quantity=100,
                    start_utc=demo_start, end_utc=demo_end, exclusive=False, status="confirmed",
                ),
                ResourceReservation(
                    resource_id=resources["Sign-in table"].id, event_id=orientation.id, quantity=2,
                    start_utc=demo_start, end_utc=demo_end, exclusive=False, status="confirmed",
                ),
            ])

            # Orientation Night packing list: projector (owned but blocked -> conflict),
            # chairs (owned, reserved), plus unowned items that flow to finance.
            db.add_all([
                PackingListItem(event_id=orientation.id, resource_id=resources["Projector"].id,
                                item_name="Projector", quantity=1, org_owned=True, source="ai"),
                PackingListItem(event_id=orientation.id, resource_id=resources["Folding chair"].id,
                                item_name="Folding chair", quantity=100, org_owned=True, source="ai"),
                PackingListItem(event_id=orientation.id, resource_id=resources["Sign-in table"].id,
                                item_name="Sign-in table", quantity=2, org_owned=True, source="ai"),
                PackingListItem(event_id=orientation.id, resource_id=None, item_name="Catering platter",
                                quantity=5, org_owned=False, source="ai", est_cost=Decimal("120.00")),
                PackingListItem(event_id=orientation.id, resource_id=None, item_name="Printed flyers",
                                quantity=200, org_owned=False, source="ai", est_cost=Decimal("0.20")),
                # Film Screening's allocation.
                PackingListItem(event_id=film.id, resource_id=resources["Projector"].id,
                                item_name="Projector", quantity=1, org_owned=True, source="ai"),
                PackingListItem(event_id=film.id, resource_id=resources["Wireless mic"].id,
                                item_name="Wireless mic", quantity=3, org_owned=True, source="ai"),
            ])

            treasurer = next(m for m in members if m.role == "treasurer")
            await _seed_finance(db, org.id, film, orientation, treasurer.id)

    print(
        f"seed: org={ORG_NAME} ({settings.org_id})\n"
        f"  scheduling: {len(members)} members, {len(venues)} venues, "
        f"{len(past_events) + 2} events (5 past + 2 demo)\n"
        f"  resources:  {len(RESOURCES)} catalogue items, 4 reservations, 5 packing-list items\n"
        f"  finance:    1 budget ($5000), 2 event budgets, 7 line items, 2 expenses\n"
        f"  demo conflicts:\n"
        f"    · resource — 'Freshman Orientation Night' blocked on Projector by 'AV Club Film Screening'\n"
        f"    · finance  — 'Freshman Orientation Night' budget over its cap\n"
        f"    · members  — exec board works Wed 14:00-18:00 next week; president has a Tue 10:00 exam"
    )


if __name__ == "__main__":
    asyncio.run(seed())
