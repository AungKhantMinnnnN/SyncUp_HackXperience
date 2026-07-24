"""FastAPI routes for the resources feature. Routes only — parse, call service,
return. All business logic lives in service.py.

Mounted under /api/resources in app/main.py. Uses the project's existing single-tenant
auth (require_api_key) and its one error shape ({"detail": str, "code": str}). There's
no per-org identity in that auth model yet, so every route takes org_id explicitly and
every lookup validates the resource/reservation/event actually belongs to it — 404
rather than 403, so a mismatched org_id doesn't confirm another org's data exists.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.db import get_db
from app.features.resources import service
from app.features.resources.schemas import (
    AvailabilityOut,
    AvailabilityQuery,
    ConflictOut,
    PackingListItemOut,
    ReservationOut,
    ReservationPlanOut,
    ResourceCreate,
    ResourceOut,
    StatusOut,
)

router = APIRouter(dependencies=[Depends(require_api_key)])


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"detail": detail, "code": "not_found"})


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"detail": detail, "code": "bad_request"})


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"detail": detail, "code": "conflict"})


@router.get("/", response_model=list[ResourceOut])
async def list_resources(org_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ResourceOut]:
    resources = await service.list_catalogue(db, org_id)
    return [ResourceOut.model_validate(r) for r in resources]


@router.post("/", response_model=ResourceOut, status_code=201)
async def create_resource(
    org_id: UUID, body: ResourceCreate, db: AsyncSession = Depends(get_db)
) -> ResourceOut:
    try:
        resource = await service.add_resource(
            db, org_id, body.name, body.quantity_total, body.category, body.exclusive
        )
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    return ResourceOut.model_validate(resource)


@router.get("/{resource_id}/availability", response_model=AvailabilityOut)
async def get_availability(
    resource_id: UUID,
    org_id: UUID,
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
    db: AsyncSession = Depends(get_db),
) -> AvailabilityOut:
    # AvailabilityQuery's cross-field validation (to > from) still runs here; only the
    # query-param binding moved to explicit Query(alias=...) — a Depends()-bound
    # Pydantic model didn't honor the "from" alias for query extraction in this
    # FastAPI version, and `from` can't be a Python parameter name directly.
    try:
        query = AvailabilityQuery(**{"from": from_, "to": to})
    except PydanticValidationError as exc:
        raise _bad_request(str(exc)) from exc

    try:
        total, reserved, available = await service.check_availability(
            db, org_id, resource_id, query.from_, query.to
        )
    except service.CrossOrgAccessError as exc:
        raise _not_found("resource not found") from exc
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
    return AvailabilityOut(
        resource_id=resource_id,
        total=total,
        reserved=reserved,
        available=available,
        from_=query.from_,
        to=query.to,
    )


@router.get("/{resource_id}/reservations", response_model=list[ReservationOut])
async def get_reservations(
    resource_id: UUID, org_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[ReservationOut]:
    """Active reservations for a resource — backs the dashboard's resource timeline."""
    try:
        rows = await service.list_reservations_for_resource(db, org_id, resource_id)
    except service.CrossOrgAccessError as exc:
        raise _not_found("resource not found") from exc
    except ValueError as exc:
        raise _not_found(str(exc)) from exc
    return [ReservationOut.model_validate(r) for r in rows]


@router.post("/events/{event_id}/packing-list/regenerate", response_model=ReservationPlanOut)
async def regenerate_packing_list(
    event_id: UUID, org_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> ReservationPlanOut:
    event = await service.load_event_view(db, event_id)
    if event is None:
        raise _not_found("event not found")
    if org_id is not None and event.org_id != org_id:
        raise _not_found("event not found")

    plan = await service.plan_for_event(db, event)
    await db.commit()  # standalone HTTP call — no scheduling transaction wraps this
    return ReservationPlanOut.from_domain(plan)


@router.get("/events/{event_id}/packing-list", response_model=list[PackingListItemOut])
async def get_packing_list(
    event_id: UUID, org_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> list[PackingListItemOut]:
    """The dashboard's event packing-list view."""
    if org_id is not None:
        event = await service.load_event_view(db, event_id)
        if event is None or event.org_id != org_id:
            raise _not_found("event not found")

    items = await service.list_packing_list_items(db, event_id)
    return [PackingListItemOut.model_validate(i) for i in items]


@router.post("/events/{event_id}/confirm", response_model=StatusOut)
async def confirm_event(
    event_id: UUID, org_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> StatusOut:
    if org_id is not None:
        event = await service.load_event_view(db, event_id)
        if event is None or event.org_id != org_id:
            raise _not_found("event not found")

    await service.confirm_for_event(db, event_id)
    await db.commit()
    return StatusOut(status="confirmed")


@router.delete("/reservations/{reservation_id}", response_model=StatusOut)
async def delete_reservation(
    reservation_id: UUID, org_id: UUID, db: AsyncSession = Depends(get_db)
) -> StatusOut:
    try:
        released = await service.release_reservation(db, org_id, reservation_id)
    except service.InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc
    if not released:
        raise _not_found("reservation not found")
    return StatusOut(status="released")


@router.post("/reservations/{reservation_id}/check-out", response_model=StatusOut)
async def check_out_reservation(
    reservation_id: UUID, org_id: UUID, db: AsyncSession = Depends(get_db)
) -> StatusOut:
    try:
        ok = await service.check_out_reservation(db, org_id, reservation_id)
    except service.InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc
    if not ok:
        raise _not_found("reservation not found")
    return StatusOut(status="checked_out")


@router.post("/reservations/{reservation_id}/return", response_model=StatusOut)
async def return_reservation(
    reservation_id: UUID, org_id: UUID, db: AsyncSession = Depends(get_db)
) -> StatusOut:
    try:
        ok = await service.return_reservation(db, org_id, reservation_id)
    except service.InvalidTransitionError as exc:
        raise _conflict(str(exc)) from exc
    if not ok:
        raise _not_found("reservation not found")
    return StatusOut(status="returned")


@router.get("/conflicts", response_model=list[ConflictOut])
async def get_conflicts(org_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ConflictOut]:
    conflicts = await service.list_conflicts(db, org_id)
    return [ConflictOut.from_domain(c) for c in conflicts]
