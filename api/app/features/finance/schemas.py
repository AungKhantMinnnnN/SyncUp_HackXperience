"""Pydantic v2 schemas for finance — API wire types and LLM output validation."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

MONEY_QUANT = Decimal("0.01")

BudgetCategory = Literal[
    "food",
    "venue",
    "equipment_rental",
    "printing",
    "materials",
    "transport",
    "contingency",
]

Verdict = Literal["OK", "TIGHT", "OVER"]

_ALLOWED_CATEGORIES = frozenset(
    {
        "food",
        "venue",
        "equipment_rental",
        "printing",
        "materials",
        "transport",
        "contingency",
    }
)


def _money_to_json_str(value: Decimal) -> str:
    """Serialize money as a fixed-scale decimal string, never a JSON float."""
    return format(value.quantize(MONEY_QUANT), "f")


MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(_money_to_json_str, return_type=str, when_used="json"),
]


# ---------------------------------------------------------------------------
# API schemas (router request/response bodies)
# ---------------------------------------------------------------------------


class LineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    description: str | None
    unit_cost: MoneyDecimal
    quantity: int
    line_total: MoneyDecimal
    source: str | None  # "ai" | "manual" | None — powers the AI-suggested badge


class EventBudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    status: str
    estimated_total: MoneyDecimal
    actual_total: MoneyDecimal
    stated_cap: MoneyDecimal | None
    lines: list[LineItemOut]


class BudgetDraft(BaseModel):
    event_budget: EventBudgetOut
    verdict: Verdict
    remaining: MoneyDecimal
    suggested_cuts: list[str] | None = None


class ApproveRequest(BaseModel):
    actor_id: UUID


class ExpenseIn(BaseModel):
    amount: MoneyDecimal
    description: str
    member_id: UUID


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: MoneyDecimal
    description: str | None
    status: str
    variance: MoneyDecimal | None


class LineItemPatch(BaseModel):
    unit_cost: MoneyDecimal | None = None
    quantity: int | None = Field(default=None, gt=0)
    description: str | None = None


# ---------------------------------------------------------------------------
# LLM output schemas (agent.py validates model JSON against these)
# ---------------------------------------------------------------------------


class DraftedLine(BaseModel):
    """One proposed line item from the model — no totals; Python computes line_total."""

    category: BudgetCategory
    description: str
    unit_cost: Decimal
    quantity: int = Field(gt=0)

    @field_validator("unit_cost")
    @classmethod
    def unit_cost_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("unit_cost must be greater than 0")
        return value

    @field_validator("category", mode="before")
    @classmethod
    def category_must_be_allowed(cls, value: object) -> object:
        if value not in _ALLOWED_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(_ALLOWED_CATEGORIES)}, got {value!r}"
            )
        return value


class DraftedLineList(BaseModel):
    lines: list[DraftedLine]


class SuggestedCut(BaseModel):
    line_description: str
    reason: str
    savings: Decimal


class SuggestedCutList(BaseModel):
    cuts: list[SuggestedCut]

class HeadroomOut(BaseModel):
    org_id: UUID
    semester: str
    allocated: MoneyDecimal
    committed: MoneyDecimal
    actual: MoneyDecimal
    remaining: MoneyDecimal
    verdict: Verdict


class BurndownPoint(BaseModel):
    date: date
    cumulative_committed: MoneyDecimal
    cumulative_actual: MoneyDecimal


class BurndownOut(BaseModel):
    org_id: UUID
    semester: str
    allocated: MoneyDecimal
    points: list[BurndownPoint]


class VarianceLine(BaseModel):
    event_title: str
    category: str
    description: str | None
    estimated: MoneyDecimal
    actual: MoneyDecimal
    variance: MoneyDecimal


class VarianceOut(BaseModel):
    org_id: UUID
    lines: list[VarianceLine]