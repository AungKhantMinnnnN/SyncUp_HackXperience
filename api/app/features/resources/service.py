"""Resources service (Member B). Never imports scheduling. Never commits inside the
functions scheduling calls — the caller owns that transaction.

Two groups of functions, per CLAUDE.md's transaction rule:

  * plan_for_event / confirm_for_event — called by scheduling inside its own confirm
    transaction. Take a session, use it, never call db.begin()/db.commit().
  * Everything else (add_resource, release_reservation, check_out_reservation, ...) —
    standalone operations nothing wraps, so each owns and commits its own transaction.

Follows docs/02-Resource-Planning-Flow.html section 3 end to end:
  1. supersede any previous AI-sourced packing list for this event (idempotency)
  2. load the org's catalogue
  3. agent.infer_requirements() proposes a packing list (real Foundry call, with a
     safe-empty-draft fallback on any failure)
  4. every proposed item becomes a packing_list_items row (source=ai)
  5. each *owned* item is checked via availability.compute() and held if any is free
  6. anything not fully available gets agent.suggest_alternatives() and a ConflictView
  7. unowned items are returned for finance to price as a rental line
  8. venue cost is computed from the event's venue, if any
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.core.types import ConflictView, EventView, ReservationPlan, UnownedItem
from app.features.resources import agent
from app.features.resources.availability import AvailabilityStatus, compute
from app.models.org import Venue
from app.models.resources import PackingListItem, Resource, ResourceReservation

logger = logging.getLogger("syncup.resources.service")

HOLD_TTL_MINUTES = 30
OVERDUE_AFTER_HOURS = 24
RESERVED_STATUSES = ("held", "confirmed", "checked_out")


class CrossOrgAccessError(PermissionError):
    """Raised when a request tries to act on another org's resource/reservation."""


class ReservationStatus(str, Enum):
    HELD = "held"
    CONFIRMED = "confirmed"
    CHECKED_OUT = "checked_out"
    RETURNED = "returned"
    OVERDUE = "overdue"
    RELEASED = "released"


class InvalidTransitionError(ValueError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"cannot transition reservation from '{current}' to '{target}'")
        self.current = current
        self.target = target


# Centralized state machine. Routes and bot commands must go through the service
# functions below (which call _transition), never set .status directly, so this table
# is the only place the reservation lifecycle can be bypassed from.
_ALLOWED_TRANSITIONS: dict[ReservationStatus, set[ReservationStatus]] = {
    ReservationStatus.HELD: {ReservationStatus.CONFIRMED, ReservationStatus.RELEASED},
    ReservationStatus.CONFIRMED: {ReservationStatus.CHECKED_OUT, ReservationStatus.RELEASED},
    ReservationStatus.CHECKED_OUT: {ReservationStatus.RETURNED, ReservationStatus.OVERDUE},
    ReservationStatus.OVERDUE: {ReservationStatus.RETURNED},
    ReservationStatus.RETURNED: set(),
    ReservationStatus.RELEASED: set(),
}


def _transition(reservation: ResourceReservation, target: ReservationStatus) -> None:
    current = ReservationStatus(reservation.status)
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(current.value, target.value)
    reservation.status = target.value


def match_by_name(catalogue: list[Resource], name: str) -> Resource | None:
    """Case-insensitive name match against the org's catalogue — pure, no I/O. This is
    the only way an agent-proposed item is ever linked to a real resource; a
    model-emitted resource_id is never trusted (there isn't even a field for one on
    InferredPackingItem)."""
    lowered = name.lower()
    for resource in catalogue:
        if resource.name.lower() == lowered:
            return resource
    return None


# --- Reading scheduling's `events` table -----------------------------------------
# Read-only, via raw SQL rather than an ORM model: resources must never import
# scheduling's Python module (one-way import rule), and no ORM Event model exists yet
# either. Declaring a reflected Table would risk colliding with Member A's eventual
# mapped class in the same Base.metadata, so this stays a plain SELECT — a read against
# a table resources doesn't own, not a write, and not a Python import of scheduling.

_EVENT_QUERY = text(
    """
    SELECT id, org_id, venue_id, title, description, start_utc, end_utc, expected_attendance
    FROM events
    WHERE id = :event_id
    """
)


_BLOCKING_EVENT_QUERY = text(
    """
    SELECT e.title
    FROM resource_reservations r
    JOIN events e ON e.id = r.event_id
    WHERE r.resource_id = :resource_id
      AND r.status IN ('held', 'confirmed', 'checked_out')
      AND r.start_utc < :end_utc
      AND r.end_utc > :start_utc
      AND (CAST(:exclude_event_id AS uuid) IS NULL OR r.event_id <> CAST(:exclude_event_id AS uuid))
    ORDER BY r.start_utc
    LIMIT 1
    """
)


async def _blocking_event_title(
    db: AsyncSession,
    resource_id: UUID,
    start_utc: datetime,
    end_utc: datetime,
    exclude_event_id: UUID | None = None,
) -> str | None:
    """The title of an event already holding this resource over [start, end) — the
    "competing event" the conflict feed shows. Read against scheduling's events table
    via raw SQL (one-way import rule: never import scheduling's model)."""
    row = (
        await db.execute(
            _BLOCKING_EVENT_QUERY,
            {
                "resource_id": resource_id,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "exclude_event_id": exclude_event_id,
            },
        )
    ).first()
    return row[0] if row else None


async def load_event_view(db: AsyncSession, event_id: UUID) -> EventView | None:
    """Read-only lookup of an event for the routes that need one (regenerate,
    confirm). Returns None if no such event exists yet."""
    row = (await db.execute(_EVENT_QUERY, {"event_id": event_id})).mappings().first()
    if row is None:
        return None
    return EventView(
        id=row["id"],
        org_id=row["org_id"],
        title=row["title"],
        description=row["description"],
        start_utc=row["start_utc"],
        end_utc=row["end_utc"],
        expected_attendance=row["expected_attendance"],
        venue_id=row["venue_id"],
    )


# --- The scheduling contract -------------------------------------------------------


async def plan_for_event(db: AsyncSession, event: EventView) -> ReservationPlan:
    """Infer packing list, reserve equipment (status=held), flag conflicts.
    Uses the passed session; must not commit.

    Idempotent: re-running this for the same event first supersedes any previous
    AI-sourced packing list items and releases the (still-held, not-yet-approved)
    reservations that went with them. Manual packing-list items and any reservation
    already 'confirmed' or later in its lifecycle are never touched — an organizer
    who already approved a hold must not have it silently unwound by a regenerate.
    """
    await db.execute(
        delete(PackingListItem).where(
            PackingListItem.event_id == event.id, PackingListItem.source == "ai"
        )
    )
    stale_holds = (
        await db.execute(
            select(ResourceReservation).where(
                ResourceReservation.event_id == event.id,
                ResourceReservation.status == "held",
            )
        )
    ).scalars()
    for reservation in stale_holds:
        _transition(reservation, ReservationStatus.RELEASED)

    catalogue = (
        (await db.execute(select(Resource).where(Resource.org_id == event.org_id))).scalars().all()
    )

    venue = await db.get(Venue, event.venue_id) if event.venue_id else None
    inferred_items = await agent.infer_requirements(db, event, catalogue, venue)

    owned: list[tuple[agent.InferredPackingItem, Resource]] = []
    unowned: list[agent.InferredPackingItem] = []

    for item in inferred_items:
        resource = match_by_name(catalogue, item.name)
        if resource is None:
            unowned.append(item)
        else:
            owned.append((item, resource))

    # Lock every owned resource FOR UPDATE up front, in a stable order (sorted by id),
    # before inserting anything that references them. Both halves matter for
    # deadlock-freedom under concurrency:
    #  - locking first (before packing_list_items below): that insert's FK to
    #    resources implicitly takes a FOR KEY SHARE lock; taking FOR UPDATE afterward
    #    would mean upgrading a lock already held, and two transactions upgrading
    #    against each other's KEY SHARE is a classic deadlock.
    #  - stable order: two transactions each needing two of the same resources, locked
    #    in different orders, is the other classic deadlock — sorting avoids it.
    locked_by_id: dict[UUID, Resource] = {}
    for _, resource in sorted(owned, key=lambda pair: pair[1].id):
        if resource.id not in locked_by_id:
            locked_by_id[resource.id] = await _lock_resource(db, resource.id)

    unowned_items: list[UnownedItem] = []

    for item, resource in owned:
        db.add(
            PackingListItem(
                event_id=event.id,
                resource_id=resource.id,
                item_name=item.name,
                quantity=item.quantity,
                org_owned=True,
                source="ai",
                est_cost=None,
            )
        )

    for item in unowned:
        est_cost = agent.to_decimal(item.estimated_unit_cost) or Decimal("0.00")
        db.add(
            PackingListItem(
                event_id=event.id,
                resource_id=None,
                item_name=item.name,
                quantity=item.quantity,
                org_owned=False,
                source="ai",
                est_cost=est_cost,
            )
        )
        unowned_items.append(UnownedItem(item_name=item.name, quantity=item.quantity, est_cost=est_cost))

    reservation_ids: list[UUID] = []
    conflicts: list[ConflictView] = []

    for item, resource in owned:
        locked = locked_by_id[resource.id]
        reserved = await _reserved_quantity(db, locked.id, event.start_utc, event.end_utc)
        result = compute(locked.quantity_total, reserved, item.quantity)

        if result.available > 0:
            reservation = ResourceReservation(
                resource_id=locked.id,
                event_id=event.id,
                quantity=result.available,
                start_utc=event.start_utc,
                end_utc=event.end_utc,
                exclusive=locked.exclusive,
                status="held",
                expires_at=now_utc() + timedelta(minutes=HOLD_TTL_MINUTES),
            )
            db.add(reservation)
            await db.flush()  # populate reservation.id without committing the caller's transaction
            reservation_ids.append(reservation.id)

        if result.status is not AvailabilityStatus.OK:
            alternatives = [
                r for r in catalogue if r.category == resource.category and r.id != resource.id
            ]
            alternative_text = await agent.suggest_alternatives(
                db,
                resource,
                event,
                requested=item.quantity,
                available=result.available,
                shortfall=result.shortfall,
                catalogue_alternatives=alternatives,
            )
            blocking_title = await _blocking_event_title(
                db, resource.id, event.start_utc, event.end_utc, exclude_event_id=event.id
            )
            conflicts.append(
                ConflictView(
                    resource_name=resource.name,
                    event_id=event.id,
                    requested=item.quantity,
                    available=result.available,
                    shortfall=result.shortfall,
                    blocking_event_title=blocking_title,
                    suggested_alternative=alternative_text,
                )
            )

    duration_hours = Decimal((event.end_utc - event.start_utc).total_seconds()) / Decimal(3600)
    venue_cost = (venue.hourly_cost * duration_hours) if venue else Decimal("0.00")

    return ReservationPlan(
        event_id=event.id,
        reservation_ids=reservation_ids,
        conflicts=conflicts,
        unowned_items=unowned_items,
        venue_cost=venue_cost,
    )


async def confirm_for_event(db: AsyncSession, event_id: UUID) -> None:
    """Promote held reservations to confirmed for an approved event.

    Expired holds are excluded from confirmation — never silently revived — and are
    released immediately rather than left dangling in a stale 'held' state.
    """
    now = now_utc()
    result = await db.execute(
        select(ResourceReservation).where(
            ResourceReservation.event_id == event_id,
            ResourceReservation.status == "held",
        )
    )
    for reservation in result.scalars():
        if reservation.expires_at is not None and reservation.expires_at <= now:
            _transition(reservation, ReservationStatus.RELEASED)
        else:
            _transition(reservation, ReservationStatus.CONFIRMED)


async def release_all_for_event(db: AsyncSession, event_id: UUID) -> None:
    """Release every held/confirmed reservation for a cancelled event. Called by
    scheduling inside its own transaction — same rules as plan_for_event/
    confirm_for_event above: must not commit."""
    result = await db.execute(
        select(ResourceReservation).where(
            ResourceReservation.event_id == event_id,
            ResourceReservation.status.in_(("held", "confirmed")),
        )
    )
    for reservation in result.scalars():
        _transition(reservation, ReservationStatus.RELEASED)


async def _lock_resource(db: AsyncSession, resource_id: UUID) -> Resource:
    """Lock the resource row for the rest of the caller's transaction. A second
    transaction calling this for the same resource_id blocks here until the first
    commits or rolls back, serializing the check-then-insert in plan_for_event."""
    result = await db.execute(select(Resource).where(Resource.id == resource_id).with_for_update())
    return result.scalar_one()


async def _reserved_quantity(db: AsyncSession, resource_id: UUID, start_utc, end_utc) -> int:
    """SUM of overlapping held/confirmed/checked_out reservations for this resource."""
    result = await db.execute(
        select(func.coalesce(func.sum(ResourceReservation.quantity), 0)).where(
            ResourceReservation.resource_id == resource_id,
            ResourceReservation.status.in_(RESERVED_STATUSES),
            ResourceReservation.start_utc < end_utc,
            ResourceReservation.end_utc > start_utc,
        )
    )
    return result.scalar_one()


# --- Standalone operations below: none of these are called by scheduling's confirm
# transaction, so — unlike plan_for_event/confirm_for_event/release_all_for_event
# above — each owns and commits its own transaction. They back the bot's admin-style
# commands, the router, and the scheduler's maintenance sweeps. ---


async def list_catalogue(db: AsyncSession, org_id: UUID) -> list[Resource]:
    """All resources an org owns. GET /api/resources?org_id= equivalent."""
    result = await db.execute(select(Resource).where(Resource.org_id == org_id))
    return list(result.scalars().all())


async def list_packing_list_items(db: AsyncSession, event_id: UUID) -> list[PackingListItem]:
    """Every packing-list item (AI and manual) for an event — the dashboard's event
    packing-list view."""
    result = await db.execute(select(PackingListItem).where(PackingListItem.event_id == event_id))
    return list(result.scalars().all())


async def find_resource_by_name(db: AsyncSession, org_id: UUID, name: str) -> Resource | None:
    result = await db.execute(
        select(Resource).where(Resource.org_id == org_id, func.lower(Resource.name) == name.lower())
    )
    return result.scalar_one_or_none()


async def add_resource(
    db: AsyncSession,
    org_id: UUID,
    name: str,
    quantity_total: int,
    category: str | None = None,
    exclusive: bool = False,
) -> Resource:
    """Add a catalogue item. POST /api/resources equivalent."""
    if quantity_total < 0:
        raise ValueError("quantity_total must be non-negative")

    resource = Resource(
        org_id=org_id,
        name=name,
        category=category,
        quantity_total=quantity_total,
        exclusive=exclusive,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return resource


async def check_availability(
    db: AsyncSession, org_id: UUID, resource_id: UUID, start_utc: datetime, end_utc: datetime
) -> tuple[int, int, int]:
    """(total, reserved, free) for a resource over a window. GET /{id}/availability
    equivalent. Raises CrossOrgAccessError if the resource belongs to another org."""
    if start_utc >= end_utc:
        raise ValueError("start_utc must be before end_utc")

    resource = await db.get(Resource, resource_id)
    if resource is None:
        raise ValueError(f"no resource with id {resource_id}")
    if resource.org_id != org_id:
        raise CrossOrgAccessError("resource belongs to a different organization")

    reserved = await _reserved_quantity(db, resource_id, start_utc, end_utc)
    return resource.quantity_total, reserved, max(resource.quantity_total - reserved, 0)


async def list_reservations_for_resource(
    db: AsyncSession, org_id: UUID, resource_id: UUID
) -> list[ResourceReservation]:
    """Active (held/confirmed/checked_out) reservations for a resource, soonest
    first. Raises CrossOrgAccessError if the resource belongs to another org."""
    resource = await db.get(Resource, resource_id)
    if resource is None:
        raise ValueError(f"no resource with id {resource_id}")
    if resource.org_id != org_id:
        raise CrossOrgAccessError("resource belongs to a different organization")

    result = await db.execute(
        select(ResourceReservation)
        .where(
            ResourceReservation.resource_id == resource_id,
            ResourceReservation.status.in_(RESERVED_STATUSES),
        )
        .order_by(ResourceReservation.start_utc)
    )
    return list(result.scalars().all())


async def list_active_reservations(
    db: AsyncSession, org_id: UUID
) -> list[tuple[ResourceReservation, str]]:
    """All active (held/confirmed/checked_out) reservations in the org, each paired with
    its resource name — backs the bot's reservation picker (autocomplete)."""
    result = await db.execute(
        select(ResourceReservation, Resource.name)
        .join(Resource, ResourceReservation.resource_id == Resource.id)
        .where(Resource.org_id == org_id, ResourceReservation.status.in_(RESERVED_STATUSES))
        .order_by(ResourceReservation.start_utc)
    )
    return [(r, name) for r, name in result.all()]


async def _get_reservation_in_org(
    db: AsyncSession, org_id: UUID, reservation_id: UUID
) -> ResourceReservation | None:
    result = await db.execute(
        select(ResourceReservation)
        .join(Resource, ResourceReservation.resource_id == Resource.id)
        .where(ResourceReservation.id == reservation_id, Resource.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def release_reservation(db: AsyncSession, org_id: UUID, reservation_id: UUID) -> bool:
    """Release a reservation. DELETE /reservations/{id} equivalent. Returns False if
    no matching row exists for this org."""
    reservation = await _get_reservation_in_org(db, org_id, reservation_id)
    if reservation is None:
        return False
    _transition(reservation, ReservationStatus.RELEASED)
    await db.commit()
    return True


async def check_out_reservation(db: AsyncSession, org_id: UUID, reservation_id: UUID) -> bool:
    """Mark a confirmed reservation as picked up on event day."""
    reservation = await _get_reservation_in_org(db, org_id, reservation_id)
    if reservation is None:
        return False
    _transition(reservation, ReservationStatus.CHECKED_OUT)
    await db.commit()
    return True


async def return_reservation(db: AsyncSession, org_id: UUID, reservation_id: UUID) -> bool:
    """Mark a checked-out (or overdue) reservation as returned."""
    reservation = await _get_reservation_in_org(db, org_id, reservation_id)
    if reservation is None:
        return False
    _transition(reservation, ReservationStatus.RETURNED)
    await db.commit()
    return True


async def list_conflicts(db: AsyncSession, org_id: UUID) -> list[ConflictView]:
    """Org-wide conflict feed. GET /conflicts?org_id= equivalent.

    There's no separate `conflicts` table — the exclusion constraint makes an actual
    overlapping double-book of an exclusive resource impossible to persist. A
    "conflict" here means a packing-list item whose actual held/confirmed/checked-out
    reservation quantity falls short of what was originally requested, derived on read
    by joining packing_list_items to its resource and its live reservations.
    """
    reserved_subq = (
        select(
            ResourceReservation.event_id,
            ResourceReservation.resource_id,
            func.coalesce(func.sum(ResourceReservation.quantity), 0).label("reserved"),
        )
        .where(ResourceReservation.status.in_(RESERVED_STATUSES))
        .group_by(ResourceReservation.event_id, ResourceReservation.resource_id)
        .subquery()
    )

    query = (
        select(PackingListItem, Resource, reserved_subq.c.reserved)
        .join(Resource, PackingListItem.resource_id == Resource.id)
        .outerjoin(
            reserved_subq,
            (reserved_subq.c.event_id == PackingListItem.event_id)
            & (reserved_subq.c.resource_id == PackingListItem.resource_id),
        )
        .where(Resource.org_id == org_id, PackingListItem.resource_id.is_not(None))
    )

    conflicts: list[ConflictView] = []
    for item, resource, reserved in (await db.execute(query)).all():
        reserved = reserved or 0
        if reserved < item.quantity:
            # N+1 over the (small) set of conflicting items — resolve the requesting
            # event's window, then find who else holds the resource in it.
            event = await load_event_view(db, item.event_id) if item.event_id else None
            blocking_title = (
                await _blocking_event_title(
                    db, resource.id, event.start_utc, event.end_utc, exclude_event_id=item.event_id
                )
                if event
                else None
            )
            conflicts.append(
                ConflictView(
                    resource_name=resource.name,
                    event_id=item.event_id,
                    requested=item.quantity,
                    available=reserved,
                    shortfall=item.quantity - reserved,
                    blocking_event_title=blocking_title,
                )
            )
    return conflicts


# --- Maintenance sweeps, called by app/jobs/scheduler.py ---------------------------


async def expire_holds(db: AsyncSession) -> int:
    """Release any held reservation past its TTL. Standalone write; commits its own
    transaction. Safe to run repeatedly — an already-released row simply won't match
    the WHERE clause on the next run."""
    now = now_utc()
    result = await db.execute(
        select(ResourceReservation).where(
            ResourceReservation.status == "held",
            ResourceReservation.expires_at.is_not(None),
            ResourceReservation.expires_at <= now,
        )
    )
    count = 0
    for reservation in result.scalars():
        _transition(reservation, ReservationStatus.RELEASED)
        count += 1
    await db.commit()
    if count:
        logger.info("expire_holds released %d reservation(s)", count)
    return count


async def mark_overdue_checkouts(db: AsyncSession) -> int:
    """Any checked-out reservation more than 24h past its window end is overdue.
    Standalone write; commits its own transaction. Safe to run repeatedly."""
    cutoff = now_utc() - timedelta(hours=OVERDUE_AFTER_HOURS)
    result = await db.execute(
        select(ResourceReservation).where(
            ResourceReservation.status == "checked_out",
            ResourceReservation.end_utc < cutoff,
        )
    )
    count = 0
    for reservation in result.scalars():
        _transition(reservation, ReservationStatus.OVERDUE)
        count += 1
    await db.commit()
    if count:
        logger.info("mark_overdue_checkouts flagged %d reservation(s)", count)
    return count
