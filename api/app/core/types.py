"""Shared dataclasses — the only cross-module contracts.

These live here (not in scheduling) so resources/finance never import scheduling.
Import direction: scheduling -> {resources, finance}. Never the reverse.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass
class EventView:
    id: UUID
    org_id: UUID
    title: str
    start_utc: datetime
    end_utc: datetime
    expected_attendance: int | None = None
    venue_id: UUID | None = None


@dataclass
class UnownedItem:
    item_name: str
    quantity: int
    est_cost: Decimal


@dataclass
class ReservationPlan:
    event_id: UUID
    reservation_ids: list[UUID] = field(default_factory=list)
    unowned_items: list[UnownedItem] = field(default_factory=list)
    venue_cost: Decimal = Decimal("0.00")


@dataclass
class BudgetDraft:
    event_budget_id: UUID
    estimated_total: Decimal
    stated_cap: Decimal | None
    verdict: str  # e.g. "within_cap" | "over_cap" | "over_allocation"
