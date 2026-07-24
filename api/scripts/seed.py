"""Idempotent dev seed — TRUNCATE then insert, so anyone resets to a known demo
state in seconds. Deterministic (per-member fixed RNG) so the demo reproduces exactly.

Single-org build: one organization (id pinned to settings.org_id), 10 members,
3 venues, ~130 busy_blocks over 3 weeks, plus past completed events (with RSVPs,
incl. repeat no-shows to exercise fairness debt) and upcoming confirmed events
(for /events + back-to-back penalties). Also seeds a small resources catalogue and
two reservations (Member B) on the same org — one exclusive item fully booked, one
pooled item partially booked, so /availability and the conflict feed have something
real to show without needing a live event yet.

Finance demo data (budgets) lands once C's models exist.

Run:  python scripts/seed.py   (against the DEV Supabase project only)
"""

import asyncio
import random
from datetime import time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.config import settings
from app.core.time import now_utc
from app.db import SessionLocal
from app.models.org import Member, Organization, Venue
from app.models.resources import Resource, ResourceReservation
from app.models.scheduling import BusyBlock, Event, EventAttendee

ORG_NAME = "Chess Club"
ORG_TZ = "Asia/Singapore"
LOCAL = ZoneInfo(ORG_TZ)  # times below are org-local; TIMESTAMPTZ stores them as UTC

# (full_name, role, priority_weight)  — weights per scoring ref (doc §4)
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
]

BUSY_KINDS = ["class", "class", "class", "work", "club", "personal"]

# (name, category, quantity_total, exclusive)
RESOURCES = [
    ("Projector", "AV", 1, True),
    ("Wireless mic", "AV", 4, False),
    ("Folding chair", "furniture", 120, False),
    ("Sign-in table", "furniture", 2, False),
    ("Event banner", "signage", 3, False),
    ("Portable speaker", "AV", 2, False),
]


def _week_monday_local():
    """Midnight org-local (SGT) on Monday of the current week — anchor for the window.
    Aware datetime, so hours added below read as local wall-clock and store as UTC."""
    t = now_utc().astimezone(LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)
    return t - timedelta(days=t.weekday())


def _build_busy_blocks(members) -> list[BusyBlock]:
    base = _week_monday_local()
    blocks: list[BusyBlock] = []
    for m in members:
        rng = random.Random(m.full_name)  # deterministic per member
        weekdays = rng.sample(range(5), 4)  # 4 of Mon-Fri carry a recurring block
        start_hour = rng.choice([9, 10, 11, 13, 14, 15, 16])  # SGT daytime
        for wd in weekdays:
            kind = rng.choice(BUSY_KINDS)
            dur = rng.choice([60, 75, 90])
            for week in range(3):  # 3 weeks
                s = base + timedelta(days=wd + 7 * week, hours=start_hour)
                blocks.append(
                    BusyBlock(
                        member_id=m.id, kind=kind, start_utc=s,
                        end_utc=s + timedelta(minutes=dur), weight=1, source="seed",
                    )
                )
        # one 2-hour exam in week 3 (drives the hard-conflict path in scoring)
        exam_day = rng.choice(range(5))
        es = base + timedelta(days=exam_day + 14, hours=rng.choice([9, 13, 15]))  # SGT daytime
        blocks.append(
            BusyBlock(
                member_id=m.id, kind="exam", start_utc=es,
                end_utc=es + timedelta(minutes=120), weight=3, source="seed",
            )
        )
    return blocks


def _build_events(org, roster, venue):
    """Past completed events (with RSVPs) + upcoming confirmed events. The last two
    members are repeat no-shows so fairness debt (>=2 of last 5) fires."""
    base = _week_monday_local()
    events: list[Event] = []
    rsvps: list[tuple[Event, Member, str]] = []
    no_show_ids = {m.id for m in roster[-2:]}

    # 5 past completed events, one per week over the previous 5 weeks (Wed 18:00 SGT)
    for k in range(5):
        s = base - timedelta(weeks=5 - k) + timedelta(days=2, hours=18)
        ev = Event(
            org_id=org.id, created_by=roster[0].id, venue_id=venue.id,
            title=f"{org.name} weekly meeting #{k + 1}",
            start_utc=s, end_utc=s + timedelta(hours=1),
            expected_attendance=len(roster), status="completed",
        )
        events.append(ev)
        for m in roster:
            missed = m.id in no_show_ids and k < 3  # 3 of 5 -> debt threshold met
            rsvps.append((ev, m, "no_show" if missed else "attended"))

    # 2 upcoming confirmed events inside the window (for /events + back-to-back)
    for k, (wd, hr) in enumerate([(1, 18), (9, 19)]):  # next Tue 18:00, wk2 Wed 19:00 SGT
        s = base + timedelta(days=wd, hours=hr)
        events.append(
            Event(
                org_id=org.id, created_by=roster[0].id, venue_id=venue.id,
                title=f"{org.name} upcoming event #{k + 1}",
                start_utc=s, end_utc=s + timedelta(hours=1),
                expected_attendance=len(roster), status="confirmed",
            )
        )
    return events, rsvps


async def seed() -> None:
    async with SessionLocal() as db:
        async with db.begin():
            # CASCADE wipes every table referencing organizations — a full dev reset.
            await db.execute(text("TRUNCATE organizations CASCADE"))

            org = Organization(
                id=settings.org_id, name=ORG_NAME, timezone=ORG_TZ,
                quiet_hours_start=time(22, 0), quiet_hours_end=time(8, 0),
            )
            db.add(org)
            await db.flush()  # org.id is settings.org_id

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
            await db.flush()  # assign member + venue ids

            blocks = _build_busy_blocks(members)
            db.add_all(blocks)

            events, rsvps = _build_events(org, members, venues[0])
            db.add_all(events)
            await db.flush()  # assign event ids for attendee FKs
            db.add_all(
                EventAttendee(
                    event_id=ev.id, member_id=m.id,
                    required=(m.role != "member"), rsvp_status=status,
                )
                for ev, m, status in rsvps
            )

            resources = {
                name: Resource(org_id=org.id, name=name, category=cat, quantity_total=qty, exclusive=excl)
                for name, cat, qty, excl in RESOURCES
            }
            db.add_all(resources.values())
            await db.flush()  # assign resource ids

            res_start = now_utc() + timedelta(days=1)
            res_end = res_start + timedelta(hours=2)
            db.add_all([
                # Projector, fully booked — /availability and /reservations should
                # show this as a hard conflict for anyone checking the same window.
                ResourceReservation(
                    resource_id=resources["Projector"].id, event_id=None,
                    quantity=1, start_utc=res_start, end_utc=res_end,
                    exclusive=True, status="confirmed",
                ),
                # Mics, partially booked — 3 of 4 reserved in the same window, so a
                # request for 2 during it should come back PARTIAL, not OK or CONFLICT.
                ResourceReservation(
                    resource_id=resources["Wireless mic"].id, event_id=None,
                    quantity=3, start_utc=res_start, end_utc=res_end,
                    exclusive=False, status="held",
                ),
            ])

    print(
        f"seed: org={ORG_NAME} ({settings.org_id}), {len(members)} members, "
        f"{len(venues)} venues, {len(blocks)} busy_blocks, {len(events)} events, "
        f"{len(rsvps)} attendees, {len(resources)} resources"
    )


if __name__ == "__main__":
    asyncio.run(seed())
