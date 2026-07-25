"""LLM tools for scheduling (doc §8). The model parses and explains — it NEVER scores.

parse_intent: natural language -> Constraints, JSON-validated, 2 retries.
explain_ranking: cosmetic rationale; never influences the ranking.
"""

import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.llm import agent_response, log_interaction
from app.core.time import now_utc
from app.features.scheduling.schemas import Constraints

_PARSE_INSTRUCTIONS = """\
You extract scheduling constraints from an organizer's request. The current UTC time is
{now}. Resolve relative dates ("next week", "before Friday") against it.

Every field is optional — use null for anything the request doesn't state. Do NOT
invent a date range when none is implied; leave window_start/window_end null and the
system will search a sensible default window.

Return ONLY a JSON object with these keys (no prose, no markdown fence):
  duration_minutes: integer or null (e.g. "3 hour" -> 180)
  window_start: ISO-8601 UTC datetime or null (earliest it could start)
  window_end: ISO-8601 UTC datetime or null (latest it could end)
  attendee_group: string or null (e.g. "exec", "all members")
  must_be_before: ISO-8601 UTC datetime or null
  preferred_time_of_day: string or null (e.g. "evening")

Request: {prompt}"""


def _extract_json(text: str) -> str:
    """Tolerate a stray markdown fence — take the outermost { ... }."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


async def parse_intent(
    prompt: str, db: AsyncSession | None = None, org_id: UUID | None = None
) -> Constraints:
    """Parse the request into Constraints. Retries twice on malformed output; never
    patches bad JSON (CLAUDE.md rule). Logs every call to ai_interactions when a
    session is provided."""
    instructions = _PARSE_INSTRUCTIONS.format(now=now_utc().isoformat(), prompt=prompt)
    last_err: Exception | None = None
    for _ in range(3):  # initial + 2 retries
        t0 = time.monotonic()
        resp = await run_in_threadpool(agent_response, instructions)
        if db is not None:
            log_interaction(
                db,
                feature="scheduling",
                prompt=instructions,
                resp=resp,
                latency_ms=int((time.monotonic() - t0) * 1000),
                org_id=org_id,
            )
        try:
            return Constraints.model_validate_json(_extract_json(resp.output_text))
        except Exception as e:  # noqa: BLE001 — validation or JSON error, both retried
            last_err = e
    raise ValueError(f"parse_intent failed after retries: {last_err}")


_RESOLVE_INSTRUCTIONS = """\
You are SyncUp's scheduling assistant. Some members are double-booked — they are
attendees of two events that overlap in time. Recommend the single best way to resolve
it in 1-2 short, concrete sentences. Prefer rescheduling the less time-critical event to
a different day (name which one to move) so nobody has to be dropped; only suggest
removing members from an event if rescheduling clearly isn't sensible. Do not invent
facts beyond what is given.

Event A: {event_a}
Event B: {event_b}
Double-booked members: {members}"""


async def recommend_member_resolution(event_a: str, event_b: str, members: list[str]) -> str:
    """LLM advice on resolving a double-booking. Falls back to a generic, honest tip."""
    instructions = _RESOLVE_INSTRUCTIONS.format(
        event_a=event_a, event_b=event_b, members=", ".join(members)
    )
    fallback = (
        f"Drop {', '.join(members)} from whichever event they're optional for, "
        "or move one event to a non-overlapping time."
    )
    try:
        resp = await run_in_threadpool(agent_response, input=instructions)
        return resp.output_text.strip() or fallback
    except Exception:  # noqa: BLE001 — LLM unreachable; honest fallback
        return fallback


def explain_ranking(proposals) -> str:
    """Human-readable rationale for the top slots. ponytail: templated, no LLM — doc §8
    says this is cosmetic only. Swap for an LLM call in Phase 21-24 if the demo wants
    warmer prose; it must still never change the ranking."""
    if not proposals:
        return "No conflict-free slots found in the requested window."
    lines = []
    for p in proposals[:3]:
        note = f" ({'; '.join(p.conflicts)})" if p.conflicts else ""
        lines.append(f"{p.start.isoformat()} — {p.attendance_pct:.0f}% weighted attendance{note}")
    return "Top options by weighted attendance:\n" + "\n".join(lines)
