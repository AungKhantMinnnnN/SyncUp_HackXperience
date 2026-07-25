

import time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.llm import agent_response, log_interaction
from app.core.types import EventView, UnownedItem

_CATEGORIES = (
    "food",
    "venue",
    "equipment_rental",
    "printing",
    "materials",
    "transport",
    "contingency",
)

_MAX_ATTEMPTS = 2  # initial call + 1 retry, per CLAUDE.md "validate + retry once"


class FinanceAgentError(Exception):
    """Raised when the model fails schema validation after the retry (doc §5)."""


# --- LLM output schemas ---------------------------------------------------------------
# No total/subtotal/estimated_total field anywhere below — Python owns that math.


class DraftedLine(BaseModel):
    """One proposed budget line. Python computes line_total = unit_cost * quantity."""

    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "food", "venue", "equipment_rental", "printing", "materials", "transport", "contingency"
    ]
    description: str
    unit_cost: Decimal
    quantity: int


class DraftedLineList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[DraftedLine]


class SuggestedCut(BaseModel):
    """One dispensable-line suggestion. Never auto-applied (doc §5) — the human decides."""

    model_config = ConfigDict(extra="forbid")

    description: str
    category: Literal[
        "food", "venue", "equipment_rental", "printing", "materials", "transport", "contingency"
    ]
    estimated_savings: Decimal
    rationale: str


class SuggestedCutList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cuts: list[SuggestedCut]


# The hosted-agent Responses endpoint rejects the `text=` structured-output param
# ("Not allowed when agent is specified"), so we ask for JSON in the prompt and parse
# it — same approach as scheduling.parse_intent and resources.infer_requirements.
_DRAFT_SCHEMA_HINT = (
    "Return ONLY this JSON object — no prose, no markdown fence:\n"
    '{"lines": [{"category": "food|venue|equipment_rental|printing|materials|transport|'
    'contingency", "description": string, "unit_cost": number, "quantity": integer}]}'
)
_CUTS_SCHEMA_HINT = (
    "Return ONLY this JSON object — no prose, no markdown fence:\n"
    '{"cuts": [{"description": string, "category": "food|venue|equipment_rental|printing|'
    'materials|transport|contingency", "estimated_savings": number, "rationale": string}]}'
)


def _extract_json(text: str) -> str:
    """Tolerate a stray markdown fence — take the outermost { ... }."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


async def _call_agent(
    prompt: str, *, feature: str, db: AsyncSession | None, org_id: UUID | None
):
    """One call to the hosted agent via app.core.llm.agent_response (string input, no
    `text=` — the agent path forbids it), logged to ai_interactions regardless of
    outcome (try/finally)."""
    t0 = time.monotonic()
    resp = None
    try:
        resp = await run_in_threadpool(agent_response, input=prompt)
        return resp
    finally:
        if db is not None:
            log_interaction(
                db,
                feature=feature,
                prompt=prompt,
                resp=resp,
                latency_ms=int((time.monotonic() - t0) * 1000),
                org_id=org_id,
            )


async def _call_with_retry(
    prompt: str,
    model_cls: type[BaseModel],
    *,
    feature: str,
    db: AsyncSession | None,
    org_id: UUID | None,
) -> BaseModel:
    """Call, validate, retry once on malformed/invalid output, then raise
    FinanceAgentError. Never patches bad JSON (CLAUDE.md rule)."""
    last_err: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        resp = await _call_agent(prompt, feature=feature, db=db, org_id=org_id)
        try:
            return model_cls.model_validate_json(_extract_json(resp.output_text))
        except (ValidationError, AttributeError, ValueError) as e:
            last_err = e
            if attempt < _MAX_ATTEMPTS - 1:
                prompt = (
                    prompt
                    + f"\n\nYour previous response failed validation with: {e}. "
                    "Return ONLY a JSON object matching the schema — no prose, no markdown fence."
                )
    raise FinanceAgentError(f"finance agent failed after retry: {last_err}")


def _priors_line(priors: dict[str, Decimal | None]) -> str:
    lines = []
    for cat in _CATEGORIES:
        val = priors.get(cat)
        lines.append(f"  {cat}: {'$' + str(val) + ' (observed avg)' if val is not None else 'no history — use a reasonable default'}")
    return "\n".join(lines)


def _unowned_items_line(unowned_items: list[UnownedItem]) -> str:
    if not unowned_items:
        return "  (none — resources module found nothing the org doesn't already own)"
    return "\n".join(
        f"  - {u.item_name}: quantity {u.quantity}" + (f" (est. cost ${u.est_cost})" if u.est_cost else "")
        for u in unowned_items
    )


_DRAFT_SYSTEM = """\
You draft an itemized budget for a student organization's event. You propose line \
items only — category, description, unit_cost, quantity. You NEVER compute a total, \
subtotal, or contingency; a separate deterministic step handles all arithmetic.

Rules:
- Every item in "Unowned items" below MUST become its own line in category \
"equipment_rental" — price it, do not invent a different item for it, and do not \
drop it.
- For any category with an observed historical average price, anchor your unit_cost \
close to that average — it reflects this org's real vendor/campus prices. Only use \
a general-knowledge default when a category shows "no history".
- Scale food quantity to the event's expected_attendance if given.
- Do not include a "contingency" line — that is added automatically afterward.
- Return ONLY a JSON object matching the schema — no prose, no markdown fence."""


async def draft_lines(
    event: EventView,
    unowned_items: list[UnownedItem],
    priors: dict[str, Decimal | None],
    cap: Decimal | None,
    *,
    db: AsyncSession | None = None,
    org_id: UUID | None = None,
) -> list[DraftedLine]:
    """LLM proposes budget line items for `event`. Pydantic-validated, retried once.
    Every number here is advisory — service.py performs all Decimal arithmetic."""
    user_content = f"""\
Event: {event.title}
Expected attendance: {event.expected_attendance if event.expected_attendance is not None else "unknown"}
Stated budget cap: {f"${cap}" if cap is not None else "none given"}

Unowned items (from the resources module — price each one, do not add or drop items):
{_unowned_items_line(unowned_items)}

Historical per-category prices for this org (anchor to these when present):
{_priors_line(priors)}"""

    prompt = f"{_DRAFT_SYSTEM}\n\n{_DRAFT_SCHEMA_HINT}\n\n{user_content}"
    result = await _call_with_retry(
        prompt, DraftedLineList, feature="finance", db=db, org_id=org_id
    )
    return result.lines


_CUTS_SYSTEM = """\
A student organization's event budget is over its allocation. Given the current \
line items and the overage amount, rank the most dispensable lines and suggest \
specific dollar savings for each. You are NOT authorizing the cut — a human decides; \
you only propose ranked, explained suggestions.

Rules:
- Never suggest cutting more than a line's own line_total (unit_cost * quantity).
- Prefer suggesting reductions to food/materials/printing quantity over cutting \
equipment_rental for items the org does not own, since those are often required.
- Return ONLY a JSON object matching the schema — no prose, no markdown fence."""


def _lines_summary(lines: list[DraftedLine]) -> str:
    return "\n".join(
        f"  - [{l.category}] {l.description}: unit_cost ${l.unit_cost} x {l.quantity} "
        f"= ${(l.unit_cost * l.quantity).quantize(Decimal('0.01'))}"
        for l in lines
    )


async def suggest_cuts(
    lines: list[DraftedLine],
    overage: Decimal,
    *,
    db: AsyncSession | None = None,
    org_id: UUID | None = None,
) -> list[SuggestedCut]:
    """LLM ranks dispensable lines to close a budget overage. Advisory only — never
    auto-applied (doc §5, "the agent advises, the human decides")."""
    user_content = f"""\
Current line items:
{_lines_summary(lines)}

Overage: ${overage} over the allowed budget. Suggest ranked cuts totaling at least \
this amount if possible."""

    prompt = f"{_CUTS_SYSTEM}\n\n{_CUTS_SCHEMA_HINT}\n\n{user_content}"
    result = await _call_with_retry(
        prompt, SuggestedCutList, feature="finance", db=db, org_id=org_id
    )
    return result.cuts