"""Integration tests against a real local Postgres (see conftest.py — auto-skipped if
unreachable). Mocks agent.infer_requirements/suggest_alternatives per test; no live
LLM call happens anywhere in this suite.
"""

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_utc
from app.core.types import EventView
from app.features.resources import agent, service
from app.models.resources import PackingListItem, Resource, ResourceReservation
from tests.conftest import TEST_DATABASE_URL


async def _make_resource(db, org_id, name, quantity_total=1, exclusive=False) -> Resource:
    resource = Resource(org_id=org_id, name=name, quantity_total=quantity_total, exclusive=exclusive)
    db.add(resource)
    await db.flush()
    return resource


async def _make_event(db, org_id, hours_from_now=24, duration_hours=2, expected_attendance=50) -> EventView:
    start = now_utc() + timedelta(hours=hours_from_now)
    end = start + timedelta(hours=duration_hours)
    result = await db.execute(
        text(
            "INSERT INTO events (org_id, title, start_utc, end_utc, expected_attendance, status) "
            "VALUES (:org_id, 'Test event', :start, :end, :attendance, 'draft') RETURNING id"
        ),
        {"org_id": org_id, "start": start, "end": end, "attendance": expected_attendance},
    )
    event_id = result.scalar_one()
    await db.commit()
    return EventView(
        id=event_id, org_id=org_id, title="Test event",
        start_utc=start, end_utc=end, expected_attendance=expected_attendance,
    )


def _one_item(name="Projector", quantity=1, cost=None):
    async def _infer(db, event, catalogue, venue=None):
        return [agent.InferredPackingItem(name=name, quantity=quantity, estimated_unit_cost=cost)]
    return _infer


async def _no_alternative(db, resource, event, *, requested, available, shortfall, catalogue_alternatives):
    return "mock alternative"


@pytest.mark.asyncio
async def test_exclusive_overlap_rejected_by_db(db, org_id):
    resource = await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    start = now_utc() + timedelta(hours=10)
    end = start + timedelta(hours=2)

    db.add(
        ResourceReservation(
            resource_id=resource.id, quantity=1, start_utc=start, end_utc=end,
            exclusive=True, status="held",
        )
    )
    await db.flush()

    db.add(
        ResourceReservation(
            resource_id=resource.id, quantity=1, start_utc=start, end_utc=end,
            exclusive=True, status="held",
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_plan_for_event_does_not_commit(db, org_id, monkeypatch):
    monkeypatch.setattr(agent, "infer_requirements", _one_item("Projector", 1))
    monkeypatch.setattr(agent, "suggest_alternatives", _no_alternative)

    await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    event = await _make_event(db, org_id)

    plan = await service.plan_for_event(db, event)
    assert len(plan.reservation_ids) == 1

    await db.rollback()

    rows = (await db.execute(select(ResourceReservation))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_unmatched_item_becomes_unowned(db, org_id, monkeypatch):
    monkeypatch.setattr(agent, "infer_requirements", _one_item("Bouncy Castle", 1, cost=200.0))
    monkeypatch.setattr(agent, "suggest_alternatives", _no_alternative)

    event = await _make_event(db, org_id)
    plan = await service.plan_for_event(db, event)

    assert plan.reservation_ids == []
    assert len(plan.unowned_items) == 1
    assert plan.unowned_items[0].item_name == "Bouncy Castle"
    assert plan.unowned_items[0].est_cost == Decimal("200.0")


@pytest.mark.asyncio
async def test_expired_hold_becomes_released(db, org_id):
    resource = await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    reservation = ResourceReservation(
        resource_id=resource.id, quantity=1,
        start_utc=now_utc(), end_utc=now_utc() + timedelta(hours=1),
        exclusive=True, status="held", expires_at=now_utc() - timedelta(minutes=1),
    )
    db.add(reservation)
    await db.commit()

    count = await service.expire_holds(db)
    assert count == 1

    await db.refresh(reservation)
    assert reservation.status == "released"


@pytest.mark.asyncio
async def test_expired_hold_cannot_be_confirmed(db, org_id):
    resource = await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    event = await _make_event(db, org_id)
    reservation = ResourceReservation(
        resource_id=resource.id, event_id=event.id, quantity=1,
        start_utc=event.start_utc, end_utc=event.end_utc,
        exclusive=True, status="held", expires_at=now_utc() - timedelta(minutes=1),
    )
    db.add(reservation)
    await db.commit()

    await service.confirm_for_event(db, event.id)
    await db.commit()

    await db.refresh(reservation)
    assert reservation.status == "released"  # not silently confirmed


@pytest.mark.asyncio
async def test_regeneration_does_not_duplicate_active_reservations(db, org_id, monkeypatch):
    monkeypatch.setattr(agent, "infer_requirements", _one_item("Projector", 1))
    monkeypatch.setattr(agent, "suggest_alternatives", _no_alternative)

    await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    event = await _make_event(db, org_id)

    plan1 = await service.plan_for_event(db, event)
    await db.commit()
    plan2 = await service.plan_for_event(db, event)
    await db.commit()

    assert len(plan1.reservation_ids) == 1
    assert len(plan2.reservation_ids) == 1

    active = (
        await db.execute(
            select(ResourceReservation).where(
                ResourceReservation.event_id == event.id,
                ResourceReservation.status.in_(("held", "confirmed")),
            )
        )
    ).scalars().all()
    assert len(active) == 1  # never two simultaneously-active holds for the same event+resource

    packing_items = (
        await db.execute(select(PackingListItem).where(PackingListItem.event_id == event.id))
    ).scalars().all()
    assert len(packing_items) == 1  # the stale AI item was superseded, not duplicated


@pytest.mark.asyncio
async def test_cross_org_access_rejected(db, org_id):
    resource = await _make_resource(db, org_id, "Projector", quantity_total=1, exclusive=True)
    other_org = uuid.uuid4()

    with pytest.raises(service.CrossOrgAccessError):
        await service.check_availability(
            db, other_org, resource.id, now_utc(), now_utc() + timedelta(hours=1)
        )

    released = await service.release_reservation(db, other_org, uuid.uuid4())
    assert released is False


@pytest.mark.asyncio
async def test_concurrent_pooled_holds_never_exceed_total(db, org_id):
    """Two near-concurrent plan_for_event calls against the same pooled resource, each
    in its own session/transaction, both wanting more than half the stock. Without
    _lock_resource()'s SELECT ... FOR UPDATE this is a real TOCTOU race (pooled
    resources have no exclusion constraint to fall back on); with it, the second
    transaction blocks until the first commits and sees the updated reserved total."""
    resource = await _make_resource(db, org_id, "Wireless mic", quantity_total=4)
    await db.commit()
    resource_id = resource.id

    start = now_utc() + timedelta(hours=10)
    end = start + timedelta(hours=2)

    engine = create_async_engine(TEST_DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _make_and_plan(title: str, quantity: int):
        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "INSERT INTO events (org_id, title, start_utc, end_utc, status) "
                    "VALUES (:org_id, :title, :start, :end, 'draft') RETURNING id"
                ),
                {"org_id": org_id, "title": title, "start": start, "end": end},
            )
            event_id = result.scalar_one()
            await session.commit()

            event = EventView(id=event_id, org_id=org_id, title=title, start_utc=start, end_utc=end)

            async def _infer(db_, ev, catalogue, venue=None):
                return [agent.InferredPackingItem(name="Wireless mic", quantity=quantity)]

            with patch.object(agent, "infer_requirements", _infer), \
                 patch.object(agent, "suggest_alternatives", _no_alternative):
                plan = await service.plan_for_event(session, event)
                await session.commit()
            return plan

    plan_a, plan_b = await asyncio.gather(
        _make_and_plan("Event A", 3),
        _make_and_plan("Event B", 3),
    )

    async with SessionLocal() as check_db:
        total_reserved = await service._reserved_quantity(check_db, resource_id, start, end)

    await engine.dispose()

    # Combined requested was 6 against a total of 4 — at least one plan must have
    # come back short, and the DB-visible total must never exceed capacity.
    assert total_reserved <= 4
    total_held = sum(len(p.reservation_ids) for p in (plan_a, plan_b))
    assert total_held >= 1  # both should still get *something* (partial availability)
