"""LLM-facing packing-list inference (Member B).

Uses the repository's existing agent integration: app.core.llm.agent_response() for
the model call, and app.core.llm.log_interaction() for the shared ai_interactions
logger every feature agent uses (not a per-feature duplicate). This module never
computes: it only turns language into a structured proposal. service.py and
availability.py own every number that actually gets persisted or decided on.

Per CLAUDE.md's LLM rules: JSON against a Pydantic schema, validate, never trust a
model-emitted ID, log every call to ai_interactions.
"""

import json
import logging
import time
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.llm import agent_response, log_interaction
from app.core.types import EventView
from app.models.org import Venue
from app.models.resources import Resource

logger = logging.getLogger("syncup.resources.agent")

INFER_SYSTEM_PROMPT = """You are the resource-planning assistant for SyncUp, an AI \
operations tool for student organizations. Given an event description and the org's \
current equipment catalogue, propose a practical packing list.

Rules:
- Scale quantities to the expected attendance (e.g. chairs, cups scale with headcount;
  a projector or sign-in table typically does not).
- Prefer items that already exist in the supplied catalogue — use the catalogue's exact
  name when an item matches, so it can be matched back to inventory.
- Only propose unowned items when something is genuinely needed and clearly absent
  from the catalogue.
- Never invent a database ID. You only ever name items; the system resolves IDs.
- Do not propose duplicate or near-duplicate items.
- Return JSON matching the given schema only — no prose outside the schema."""

ALTERNATIVES_SYSTEM_PROMPT = """You are the resource-planning assistant for SyncUp. A \
requested resource is short for an event. Using only the facts given to you, write one \
short, concrete sentence suggesting what the organizer should do next.

Rules:
- Use only the facts supplied in the context. Do not invent who is holding the resource,
  what club has it, or any detail not explicitly given.
- If catalogue alternatives are supplied, prefer suggesting one of them by name.
- If nothing concrete is available, suggest a generic next step (e.g. checking with the
  venue or department) without asserting a specific outcome.
- One sentence. No preamble, no markdown."""


class InferredPackingItem(BaseModel):
    name: str
    quantity: int
    category: str | None = None
    estimated_unit_cost: float | None = None
    reasoning: str | None = None


class InferredPackingList(BaseModel):
    items: list[InferredPackingItem]


def _catalogue_context(catalogue: list[Resource]) -> list[dict]:
    return [
        {"name": r.name, "category": r.category, "quantity_total": r.quantity_total, "exclusive": r.exclusive}
        for r in catalogue
    ]


def _safe_log(db: AsyncSession, *, feature: str, prompt: str, resp, latency_ms: int, org_id) -> None:
    """log_interaction() itself isn't wrapped for failure — a logging problem must
    never take down packing-list inference, so guard the call here instead."""
    try:
        log_interaction(db, feature=feature, prompt=prompt, resp=resp, latency_ms=latency_ms, org_id=org_id)
    except Exception:
        logger.warning("failed to log ai_interaction for feature=%s", feature, exc_info=True)


async def infer_requirements(
    db: AsyncSession,
    event: EventView,
    catalogue: list[Resource],
    venue: Venue | None = None,
) -> list[InferredPackingItem]:
    """Infer what an event needs from its description, using the org's own catalogue
    as grounding context so proposals are things the org plausibly owns.

    Falls back to an empty list (a safe, empty draft) on any failure — missing Foundry
    config, a timeout, or a response that doesn't validate against the schema. An empty
    draft is always safer than persisting a malformed guess.
    """
    context = {
        "event": {
            "title": event.title,
            "expected_attendance": event.expected_attendance,
            "start_utc": event.start_utc.isoformat(),
            "end_utc": event.end_utc.isoformat(),
        },
        "venue": {"name": venue.name, "capacity": venue.capacity} if venue else None,
        "catalogue": _catalogue_context(catalogue),
    }

    started = time.monotonic()
    response = None
    try:
        response = await run_in_threadpool(
            agent_response,
            input=[
                {"role": "system", "content": INFER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "packing_list",
                    "schema": InferredPackingList.model_json_schema(),
                    "strict": True,
                }
            },
        )
        parsed = InferredPackingList.model_validate_json(response.output_text)
        return parsed.items
    except Exception:
        logger.warning("infer_requirements failed for event org_id=%s", event.org_id, exc_info=True)
        return []
    finally:
        _safe_log(
            db,
            feature="resources.infer_requirements",
            prompt=json.dumps(context),
            resp=response,
            latency_ms=int((time.monotonic() - started) * 1000),
            org_id=event.org_id,
        )


async def suggest_alternatives(
    db: AsyncSession,
    resource: Resource,
    event: EventView,
    *,
    requested: int,
    available: int,
    shortfall: int,
    catalogue_alternatives: list[Resource],
) -> str:
    """Suggest a next step when a resource can't fully cover an event's request.
    Falls back to a generic, honest message on any failure.
    """
    context = {
        "resource_name": resource.name,
        "requested_quantity": requested,
        "available_quantity": available,
        "shortfall": shortfall,
        "catalogue_alternatives": [
            {"name": r.name, "category": r.category} for r in catalogue_alternatives
        ],
    }

    fallback = f"{resource.name} is short by {shortfall} for this window — check with the org's equipment desk."

    started = time.monotonic()
    response = None
    try:
        response = await run_in_threadpool(
            agent_response,
            input=[
                {"role": "system", "content": ALTERNATIVES_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context)},
            ],
        )
        return response.output_text.strip() or fallback
    except Exception:
        logger.warning("suggest_alternatives failed for resource=%s", resource.name, exc_info=True)
        return fallback
    finally:
        _safe_log(
            db,
            feature="resources.suggest_alternatives",
            prompt=json.dumps(context),
            resp=response,
            latency_ms=int((time.monotonic() - started) * 1000),
            org_id=event.org_id,
        )


def to_decimal(value: float | None) -> Decimal | None:
    """Convert an agent-proposed cost (plain float from the model) to Decimal at the
    boundary, immediately, so nothing downstream ever touches a float for money."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
