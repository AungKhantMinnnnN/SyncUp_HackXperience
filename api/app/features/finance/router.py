"""Read-only finance endpoints for the dashboard demo.

Raw SQL on purpose: finance's ORM models don't exist yet (Member C). The tables do
(schema.sql). Money is serialized as strings (golden rule 6). Replace with Member C's
real router + service when the finance module lands.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db

router = APIRouter()


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)) -> dict:
    budget = (
        await db.execute(
            text(
                "SELECT id, semester, total_allocated, currency FROM budgets "
                "WHERE org_id = :org ORDER BY created_at DESC LIMIT 1"
            ),
            {"org": settings.org_id},
        )
    ).mappings().first()
    if budget is None:
        return {"semester": None, "total_allocated": "0.00", "currency": "USD",
                "committed": "0.00", "spent": "0.00", "events": []}

    event_rows = (
        await db.execute(
            text(
                "SELECT eb.id, eb.estimated_total, eb.actual_total, eb.stated_cap, eb.status, "
                "e.title FROM event_budgets eb JOIN events e ON e.id = eb.event_id "
                "WHERE eb.budget_id = :b ORDER BY eb.estimated_total DESC"
            ),
            {"b": budget["id"]},
        )
    ).mappings().all()

    events = []
    committed = Decimal("0")
    for eb in event_rows:
        lines = (
            await db.execute(
                text(
                    "SELECT category, description, line_total FROM budget_line_items "
                    "WHERE event_budget_id = :e ORDER BY line_total DESC"
                ),
                {"e": eb["id"]},
            )
        ).mappings().all()
        committed += eb["estimated_total"] or Decimal("0")
        cap = eb["stated_cap"]
        events.append({
            "event_title": eb["title"],
            "estimated_total": str(eb["estimated_total"]),
            "actual_total": str(eb["actual_total"]),
            "stated_cap": str(cap) if cap is not None else None,
            "status": eb["status"],
            "over_cap": cap is not None and eb["estimated_total"] > cap,
            "line_items": [
                {"category": ln["category"], "description": ln["description"],
                 "line_total": str(ln["line_total"])}
                for ln in lines
            ],
        })

    spent = (
        await db.execute(
            text(
                "SELECT COALESCE(SUM(ex.amount), 0) FROM expenses ex "
                "JOIN event_budgets eb ON eb.id = ex.event_budget_id "
                "WHERE eb.budget_id = :b AND ex.status IN ('approved', 'reimbursed')"
            ),
            {"b": budget["id"]},
        )
    ).scalar_one()

    return {
        "semester": budget["semester"],
        "total_allocated": str(budget["total_allocated"]),
        "currency": budget["currency"],
        "committed": str(committed),
        "spent": str(spent),
        "events": events,
    }
