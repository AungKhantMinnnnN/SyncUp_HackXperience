"""Pydantic request/response + LLM output schemas (doc §7, §8).

Constraints is the LLM parse target (agent.py); service.py maps it to the pure
scoring.Constraints dataclass. Datetimes on the wire are ISO-8601 UTC.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class Constraints(BaseModel):
    """LLM output — validated, never trusted for numbers. Fields per doc §8."""

    duration_minutes: int
    window_start: datetime
    window_end: datetime
    attendee_group: str | None = None
    must_be_before: datetime | None = None
    preferred_time_of_day: str | None = None


class OrgOut(BaseModel):
    id: UUID
    name: str
    timezone: str


class MemberOut(BaseModel):
    id: UUID
    full_name: str
    role: str


class BusyOut(BaseModel):
    member_id: UUID
    kind: str
    start_utc: datetime
    end_utc: datetime


class CalendarOut(BaseModel):
    members: list[MemberOut] = []
    busy: list[BusyOut] = []


class CreateRequestIn(BaseModel):
    prompt: str
    member_id: UUID | None = None


class CreateRequestOut(BaseModel):
    request_id: UUID
    status: str


class ProposalOut(BaseModel):
    id: UUID
    start_utc: datetime
    end_utc: datetime
    score: float | None = None
    attendance_pct: float | None = None
    rank: int | None = None
    conflicts: list[str] = []
    available_members: list[str] = []


class RequestStatusOut(BaseModel):
    request_id: UUID
    status: str
    parsed_constraints: dict | None = None
    proposals: list[ProposalOut] = []


class ConfirmIn(BaseModel):
    actor_id: UUID | None = None


class EventOut(BaseModel):
    id: UUID
    title: str
    start_utc: datetime
    end_utc: datetime
    status: str


class ReservationsOut(BaseModel):
    reservation_ids: list[UUID] = []
    unowned_items: list[dict] = []
    venue_cost: str  # money as string (golden rule 6)


class BudgetOut(BaseModel):
    event_budget_id: UUID
    estimated_total: str
    stated_cap: str | None = None
    verdict: str


class EventPlanOut(BaseModel):
    """POST /proposals/{id}/confirm response — event + reservations + budget in one
    payload, because it is one transaction (doc §6, §7)."""

    event: EventOut
    reservations: ReservationsOut
    budget: BudgetOut


class AvailabilityCell(BaseModel):
    day: str  # ISO date
    hour: int  # 0-23 UTC
    free_count: int


class AvailabilityOut(BaseModel):
    member_count: int
    cells: list[AvailabilityCell] = []


class EventAllocation(BaseModel):
    item_name: str
    quantity: int
    org_owned: bool


class EventListItem(BaseModel):
    id: UUID
    title: str
    start_utc: datetime
    end_utc: datetime
    status: str
    venue_id: UUID | None = None
    members: list[str] = []
    items: list[EventAllocation] = []
