"""Finance routes (Member C). Routes only — parse, call service, return.
Mounted at /api/finance in app/main.py. Every route requires X-API-Key.
"""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import require_api_key
from app.db import get_db
from app.features.finance import service
from app.features.finance.schemas import (
    ApproveRequest,
    BudgetDraft,
    BurndownOut,
    BurndownPoint,
    EventBudgetOut,
    ExpenseIn,
    ExpenseOut,
    HeadroomOut,
    LineItemOut,
    LineItemPatch,
    VarianceLine,
    VarianceOut,
)

router = APIRouter(dependencies=[Depends(require_api_key)])


def _eb_out(eb, lines) -> EventBudgetOut:
    return EventBudgetOut(
        id=eb.id,
        event_id=eb.event_id,
        status=eb.status,
        estimated_total=eb.estimated_total,
        actual_total=eb.actual_total,
        stated_cap=eb.stated_cap,
        lines=[LineItemOut.model_validate(l) for l in lines],
    )


# ---------------------------------------------------------------------------
# Existing dashboard summary — kept as-is (raw SQL, no response_model) since it
# predates schemas.py and the dashboard may still depend on this exact shape.
# ---------------------------------------------------------------------------


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
                # DISTINCT ON: one row per event — the latest non-cancelled budget —
                # so a superseded/regenerated budget doesn't double-count or double-list.
                "SELECT DISTINCT ON (eb.event_id) eb.id, eb.estimated_total, eb.actual_total, "
                "eb.stated_cap, eb.status, e.title "
                "FROM event_budgets eb JOIN events e ON e.id = eb.event_id "
                "WHERE eb.budget_id = :b AND eb.status <> 'cancelled' "
                "ORDER BY eb.event_id, eb.created_at DESC"
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


# ---------------------------------------------------------------------------
# Real finance API surface (doc §8). Each route is a thin wrapper over service.py.
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/budget", response_model=EventBudgetOut)
async def get_event_budget(event_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await service.get_event_budget(db, event_id)
    if result is None:
        raise HTTPException(404, detail={"detail": "No budget for this event", "code": "not_found"})
    return _eb_out(*result)


@router.post("/events/{event_id}/budget/regenerate", response_model=BudgetDraft)
async def regenerate_budget(event_id: UUID, db: AsyncSession = Depends(get_db)):
    try:
        draft = await service.regenerate(db, event_id)
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    return BudgetDraft(
        event_budget=_eb_out(draft.event_budget, draft.lines),
        verdict=draft.verdict,
        remaining=draft.remaining,
        suggested_cuts=draft.suggested_cuts,
    )


@router.patch("/budgets/{budget_id}/lines/{line_id}", response_model=LineItemOut)
async def patch_line(
    budget_id: UUID, line_id: UUID, body: LineItemPatch, db: AsyncSession = Depends(get_db)
):
    try:
        line = await service.patch_line_item(db, budget_id, line_id, body.model_dump(exclude_unset=True))
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    return LineItemOut.model_validate(line)


@router.post("/budgets/{budget_id}/approve", response_model=EventBudgetOut)
async def approve_budget(budget_id: UUID, body: ApproveRequest, db: AsyncSession = Depends(get_db)):
    try:
        eb = await service.approve(db, budget_id, body.actor_id)
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    except service.InvalidBudgetStatus as e:
        raise HTTPException(409, detail={"detail": str(e), "code": "invalid_status"})
    lines = await service.get_lines(db, eb.id)
    return _eb_out(eb, lines)


@router.post("/budgets/{budget_id}/expenses", response_model=ExpenseOut)
async def log_expense(budget_id: UUID, body: ExpenseIn, db: AsyncSession = Depends(get_db)):
    try:
        expense = await service.log_expense(db, budget_id, body.amount, body.description, body.member_id)
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    return ExpenseOut.model_validate(expense)


@router.get("/headroom", response_model=HeadroomOut)
async def headroom_endpoint(org_id: UUID, semester: str, db: AsyncSession = Depends(get_db)):
    try:
        budget_row, committed, actual, result = await service.get_headroom(db, org_id, semester)
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    return HeadroomOut(
        org_id=org_id,
        semester=semester,
        allocated=budget_row.total_allocated,
        committed=committed,
        actual=actual,
        remaining=result.remaining,
        verdict=result.verdict,
    )


@router.get("/burndown", response_model=BurndownOut)
async def burndown_endpoint(org_id: UUID, semester: str, db: AsyncSession = Depends(get_db)):
    try:
        budget_row, points = await service.get_burndown(db, org_id, semester)
    except LookupError as e:
        raise HTTPException(404, detail={"detail": str(e), "code": "not_found"})
    return BurndownOut(
        org_id=org_id,
        semester=semester,
        allocated=budget_row.total_allocated,
        points=[
            BurndownPoint(date=d, cumulative_committed=c, cumulative_actual=a) for d, c, a in points
        ],
    )


@router.get("/variance", response_model=VarianceOut)
async def variance_endpoint(org_id: UUID, db: AsyncSession = Depends(get_db)):
    rows = await service.get_variance(db, org_id)
    return VarianceOut(
        org_id=org_id,
        lines=[
            VarianceLine(
                event_title=r["event_title"],
                category=r["category"],
                description=r["description"],
                estimated=r["estimated"],
                actual=r["actual"],
                variance=r["actual"] - r["estimated"],
            )
            for r in rows
        ],
    )