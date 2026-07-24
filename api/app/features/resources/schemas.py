"""Pydantic request/response schemas for the resources router.

Money on the wire as strings, datetimes as ISO-8601 UTC — per CLAUDE.md's wire
conventions. Domain dataclasses (EventView, ReservationPlan, ConflictView, ...) stay
in app/core/types.py, since those are the cross-module contract with scheduling; the
schemas here are purely the HTTP-facing shapes.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.types import ConflictView, ReservationPlan, UnownedItem


class ResourceCreate(BaseModel):
    name: str = Field(min_length=1)
    quantity_total: int = Field(ge=0)
    category: str | None = None
    exclusive: bool = False


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    category: str | None
    quantity_total: int
    exclusive: bool
    condition: str | None
    replacement_cost: Decimal | None
    created_at: datetime


class AvailabilityQuery(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime

    @field_validator("to")
    @classmethod
    def _to_after_from(cls, to: datetime, info) -> datetime:
        start = info.data.get("from_")
        if start is not None and to <= start:
            raise ValueError("'to' must be after 'from'")
        return to


class AvailabilityOut(BaseModel):
    resource_id: UUID
    total: int
    reserved: int
    available: int
    from_: datetime = Field(serialization_alias="from")
    to: datetime


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_id: UUID
    event_id: UUID | None
    quantity: int
    start_utc: datetime
    end_utc: datetime
    exclusive: bool
    status: str
    expires_at: datetime | None


class PackingListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    resource_id: UUID | None
    item_name: str
    quantity: int
    org_owned: bool
    source: str
    est_cost: Decimal | None


class UnownedItemOut(BaseModel):
    item_name: str
    quantity: int
    est_cost: Decimal

    @classmethod
    def from_domain(cls, item: UnownedItem) -> "UnownedItemOut":
        return cls(item_name=item.item_name, quantity=item.quantity, est_cost=item.est_cost)


class ConflictOut(BaseModel):
    resource_name: str
    event_id: UUID | None
    requested: int
    available: int
    shortfall: int
    blocking_event_title: str | None
    suggested_alternative: str | None

    @classmethod
    def from_domain(cls, conflict: ConflictView) -> "ConflictOut":
        return cls(
            resource_name=conflict.resource_name,
            event_id=conflict.event_id,
            requested=conflict.requested,
            available=conflict.available,
            shortfall=conflict.shortfall,
            blocking_event_title=conflict.blocking_event_title,
            suggested_alternative=conflict.suggested_alternative,
        )


class ReservationPlanOut(BaseModel):
    event_id: UUID
    reservation_ids: list[UUID]
    conflicts: list[ConflictOut]
    unowned_items: list[UnownedItemOut]
    venue_cost: Decimal

    @classmethod
    def from_domain(cls, plan: ReservationPlan) -> "ReservationPlanOut":
        return cls(
            event_id=plan.event_id,
            reservation_ids=plan.reservation_ids,
            conflicts=[ConflictOut.from_domain(c) for c in plan.conflicts],
            unowned_items=[UnownedItemOut.from_domain(u) for u in plan.unowned_items],
            venue_cost=plan.venue_cost,
        )


class StatusOut(BaseModel):
    status: str
