"""SyncUp MCP server — exposes SyncUp's capabilities to an MCP client
(Claude Desktop/Code, agents). A thin adapter over service.py, exactly like the
Discord bot: no business logic, no transactions of its own. Each tool opens a session
with `with_session` and calls the same service functions the REST routes call.

Additive — REST/FastAPI stays for the dashboard. Single-org: org is settings.org_id.

Run:  python -m app.mcp        (stdio transport)
Inspect:  mcp dev app/mcp/server.py

Claude Desktop config:
{ "mcpServers": { "syncup": {
    "command": "python", "args": ["-m", "app.mcp"],
    "cwd": "/…/SyncUp_HackXperience/api",
    "env": { "DATABASE_URL": "…pooler…" } } } }
`az login` is only needed for the LLM-backed tools (plan_meeting, draft_budget).
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time import now_utc
from app.db import with_session
from app.features.finance import service as fin
from app.features.resources import service as res
from app.features.scheduling import service as sched

try:  # ToolError renders as a clean MCP error; fall back if the SDK path differs.
    from mcp.server.fastmcp.exceptions import ToolError
except Exception:  # pragma: no cover

    class ToolError(RuntimeError):
        pass


mcp = FastMCP("SyncUp")

# Known service exceptions -> friendly, client-facing messages. Others fall through to
# their own str(). Matched by class name so we don't import each exception here.
_FRIENDLY = {
    "AlreadyConfirmed": "That proposal is already confirmed.",
    "CrossOrgAccessError": "That item belongs to another organization.",
    "LookupError": "Not found.",
}


def _explain(exc: Exception) -> str:
    name = type(exc).__name__
    return _FRIENDLY.get(name, str(exc) or name)


async def _run_tool(fn: Callable[[AsyncSession], Awaitable]):
    """Open a session, run `fn`, and map any failure to a clean MCP tool error. A
    ToolError raised inside `fn` (e.g. a not-found sentinel) passes through as-is."""
    try:
        return await with_session(fn)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 — tool boundary
        raise ToolError(_explain(exc)) from exc


async def _officer_id(db: AsyncSession):
    """A member to attribute finance actions to (no auth/session in this build).
    Prefers treasurer/president, else any member."""
    row = (
        await db.execute(
            text(
                "SELECT id FROM members WHERE org_id = :o "
                "AND role IN ('treasurer', 'president') ORDER BY role LIMIT 1"
            ),
            {"o": settings.org_id},
        )
    ).first()
    if row is None:
        row = (
            await db.execute(
                text("SELECT id FROM members WHERE org_id = :o LIMIT 1"), {"o": settings.org_id}
            )
        ).first()
    if row is None:
        raise ToolError("No members in this organization.")
    return row[0]


# --- Scheduling -------------------------------------------------------------------


@mcp.tool()
async def plan_meeting(prompt: str) -> dict:
    """Plan a meeting from a plain-English description (e.g. '2 hour exec meeting next
    week before Friday'). Returns ranked, conflict-free proposed slots. Use confirm_slot
    with a proposal id to commit one."""

    async def _run(db):
        request_id, status = await sched.create_request(db, prompt, None)
        if status == "failed":
            return {"status": "failed", "detail": "Could not parse that request."}
        proposals = await sched.get_proposals(db, request_id)
        return {
            "status": status,
            "proposals": [
                {
                    "id": str(p.id),
                    "rank": p.rank,
                    "start_utc": p.start_utc.isoformat(),
                    "end_utc": p.end_utc.isoformat(),
                    "attendance_pct": float(p.attendance_pct or 0),
                    "available_members": (p.conflicts or {}).get("free", []),
                }
                for p in proposals
            ],
        }

    return await _run_tool(_run)


@mcp.tool()
async def confirm_slot(proposal_id: str) -> dict:
    """Confirm a proposed slot by id. One atomic transaction: creates the event, holds
    resources, and drafts the budget together."""

    async def _run(db):
        plan = await sched.confirm_proposal(db, UUID(proposal_id), None)
        return {
            "event": plan.event.title,
            "start_utc": plan.event.start_utc.isoformat(),
            "reservations_held": len(plan.reservations.reservation_ids),
            "budget_verdict": plan.budget.verdict,
        }

    return await _run_tool(_run)


@mcp.tool()
async def list_upcoming_events(days: int = 14) -> list[dict]:
    """Upcoming events with the members and items allocated to each."""
    now = now_utc()

    async def _run(db):
        out = []
        for e in await sched.list_events(db, now, now + timedelta(days=days)):
            members, items = await sched.event_details(db, e.id)
            out.append({
                "title": e.title,
                "start_utc": e.start_utc.isoformat(),
                "status": e.status,
                "members": members,
                "items": [f"{i.item_name} x{i.quantity}" for i in items],
            })
        return out

    return await _run_tool(_run)


# --- Resources --------------------------------------------------------------------


@mcp.tool()
async def check_resource(name: str, from_iso: str, to_iso: str) -> dict:
    """How many of a named resource are free in a window. Times are ISO-8601 UTC
    (e.g. 2026-07-25T10:00:00Z)."""

    async def _run(db):
        resource = await res.find_resource_by_name(db, settings.org_id, name)
        if resource is None:
            raise ToolError(f"No resource named {name!r}.")
        total, reserved, free = await res.check_availability(
            db, settings.org_id, resource.id,
            datetime.fromisoformat(from_iso), datetime.fromisoformat(to_iso),
        )
        return {"resource": resource.name, "total": total, "reserved": reserved, "free": free}

    return await _run_tool(_run)


@mcp.tool()
async def list_inventory() -> list[dict]:
    """The org's equipment catalogue."""

    async def _run(db):
        items = await res.list_catalogue(db, settings.org_id)
        return [
            {"name": r.name, "category": r.category, "quantity_total": r.quantity_total,
             "exclusive": r.exclusive}
            for r in items
        ]

    return await _run_tool(_run)


@mcp.tool()
async def resource_conflicts() -> list[dict]:
    """Resources short of what an event's packing list requested, with the event that's
    blocking each."""

    async def _run(db):
        conflicts = await res.list_conflicts(db, settings.org_id)
        return [
            {"resource": c.resource_name, "requested": c.requested, "available": c.available,
             "shortfall": c.shortfall, "blocked_by": c.blocking_event_title}
            for c in conflicts
        ]

    return await _run_tool(_run)


@mcp.tool()
async def add_resource(
    name: str, quantity: int, category: str | None = None, exclusive: bool = False
) -> dict:
    """Add an item to the equipment catalogue. `exclusive` = only one can be used at a
    time (a room, the one projector)."""

    async def _run(db):
        resource = await res.add_resource(db, settings.org_id, name, quantity, category, exclusive)
        return {"id": str(resource.id), "name": resource.name,
                "quantity_total": resource.quantity_total, "exclusive": resource.exclusive}

    return await _run_tool(_run)


@mcp.tool()
async def release_reservation(reservation_id: str) -> dict:
    """Release a held or confirmed reservation, freeing the resource."""

    async def _run(db):
        released = await res.release_reservation(db, settings.org_id, UUID(reservation_id))
        if not released:
            raise ToolError("No reservation with that id in this organization.")
        return {"released": True}

    return await _run_tool(_run)


# --- Finance ----------------------------------------------------------------------


@mcp.tool()
async def budget_headroom() -> dict:
    """Semester budget headroom: allocated vs. committed vs. spent, and the verdict."""

    async def _run(db):
        row = (
            await db.execute(
                text(
                    "SELECT semester FROM budgets WHERE org_id = :o "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"o": settings.org_id},
            )
        ).first()
        if row is None:
            raise ToolError("No semester budget set up.")
        semester = row[0]
        budget_row, committed, actual, result = await fin.get_headroom(db, settings.org_id, semester)
        return {
            "semester": semester,
            "allocated": str(budget_row.total_allocated),
            "committed": str(committed),
            "spent": str(actual),
            "remaining": str(result.remaining),
            "verdict": result.verdict,
        }

    return await _run_tool(_run)


@mcp.tool()
async def draft_budget(event_id: str) -> dict:
    """(Re)draft an event's itemized budget with the LLM, check it against the semester
    allocation, and return the verdict + line items. Needs `az login`."""

    async def _run(db):
        draft = await fin.regenerate(db, UUID(event_id))
        return {
            "event_budget_id": str(draft.event_budget.id),
            "estimated_total": str(draft.event_budget.estimated_total),
            "verdict": draft.verdict,
            "remaining": str(draft.remaining),
            "suggested_cuts": draft.suggested_cuts or [],
            "lines": [
                {"category": ln.category, "description": ln.description,
                 "line_total": str(ln.line_total)}
                for ln in draft.lines
            ],
        }

    return await _run_tool(_run)


@mcp.tool()
async def approve_budget(budget_id: str) -> dict:
    """Approve an event budget (draft -> approved)."""

    async def _run(db):
        actor = await _officer_id(db)
        eb = await fin.approve(db, UUID(budget_id), actor)
        return {"status": eb.status, "estimated_total": str(eb.estimated_total)}

    return await _run_tool(_run)


@mcp.tool()
async def log_expense(budget_id: str, amount: str, description: str) -> dict:
    """Record an expense against an event budget. `amount` is a decimal string (e.g.
    '287.50')."""

    async def _run(db):
        member = await _officer_id(db)
        expense = await fin.log_expense(db, UUID(budget_id), Decimal(amount), description, member)
        return {"id": str(expense.id), "amount": str(expense.amount), "status": expense.status}

    return await _run_tool(_run)
