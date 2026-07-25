"""Finance service (Member C). Never imports scheduling — receives EventView, the
shared cross-module contract type, instead. Never commits inside draft_for_event();
scheduling owns that transaction. Money is Decimal everywhere.
"""

import difflib
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_utc
from app.core.types import BudgetDraft, EventView, ReservationPlan, UnownedItem
from app.features.finance import agent, headroom
from app.models.finance import Budget, BudgetLineItem, EventBudget, Expense

_CATEGORIES = (
    "food",
    "venue",
    "equipment_rental",
    "printing",
    "materials",
    "transport",
    "contingency",
)
_PRIOR_WINDOW_DAYS = 365  # doc §5: "last 12 months"
_MATCH_THRESHOLD = 0.35  # log_expense: minimum similarity to accept a line-item match


class NoSemesterBudget(Exception):
    """Raised by draft_for_event when the org has no `budgets` row to draft against."""


class InvalidBudgetStatus(Exception):
    """Raised by approve() when the event_budget isn't currently 'draft'."""


async def _historical_unit_cost(db: AsyncSession, org_id: UUID) -> dict[str, Decimal | None]:
    """category -> AVG(unit_cost) over the org's line items in the last 12 months.
    None for any category with no history (agent.py anchors to these when present,
    falls back to a general default otherwise)."""
    since = now_utc() - timedelta(days=_PRIOR_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(BudgetLineItem.category, func.avg(BudgetLineItem.unit_cost))
            .join(EventBudget, BudgetLineItem.event_budget_id == EventBudget.id)
            .join(Budget, EventBudget.budget_id == Budget.id)
            .where(Budget.org_id == org_id, BudgetLineItem.created_at > since)
            .group_by(BudgetLineItem.category)
        )
    ).all()
    observed = dict(rows)
    return {cat: observed.get(cat) for cat in _CATEGORIES}


async def _current_budget(db: AsyncSession, org_id: UUID) -> Budget | None:
    """The org's most recently created `budgets` row, treated as 'the current
    semester'. schema.sql has no explicit semester date range; this mirrors the same
    latest-by-created_at heuristic used elsewhere in this module."""
    return (
        await db.execute(
            select(Budget).where(Budget.org_id == org_id).order_by(Budget.created_at.desc())
        )
    ).scalars().first()


async def _committed_and_actual(db: AsyncSession, budget_id: UUID) -> tuple[Decimal, Decimal]:
    """Shared by draft_for_event, regenerate, and get_headroom so the semester math
    never drifts out of sync between them."""
    # committed: joins scheduling's `events` (to exclude budgets of cancelled/completed
    # events) — kept as raw SQL, the same cross-module read pattern resources uses,
    # since finance must not import scheduling's ORM model (one-way import rule).
    committed = Decimal(
        (
            await db.execute(
                text(
                    """
                    SELECT COALESCE(SUM(eb.estimated_total), 0)
                    FROM event_budgets eb
                    JOIN events e ON e.id = eb.event_id
                    WHERE eb.status = 'approved'
                      AND e.status IN ('draft', 'confirmed')
                      AND eb.budget_id = :budget_id
                    """
                ),
                {"budget_id": budget_id},
            )
        ).scalar_one()
    )
    # actual: finance-only tables -> ORM.
    actual = Decimal(
        (
            await db.execute(
                select(func.coalesce(func.sum(Expense.amount), 0))
                .join(EventBudget, EventBudget.id == Expense.event_budget_id)
                .where(
                    EventBudget.budget_id == budget_id,
                    Expense.status.in_(("approved", "reimbursed")),
                )
            )
        ).scalar_one()
    )
    return committed, actual


async def draft_for_event(db: AsyncSession, event: EventView, plan: ReservationPlan) -> BudgetDraft:
    """Called by scheduling inside its confirm transaction (doc §6). Drafts an itemized
    budget, checks it against the semester allocation, persists a draft event_budget +
    line items.

    MUST NOT call db.commit() or db.rollback() — only db.flush() for generated IDs.
    Scheduling owns the transaction; if a later step (e.g. an unrelated failure) rolls
    back, this draft rolls back with it rather than leaving an orphaned budget.

    Returns app.core.types.BudgetDraft exactly as scheduling expects it — 4 fields
    only. Do NOT add remaining/suggested_cuts here; that broke every caller of this
    function last time. The richer, API-facing schemas.BudgetDraft is assembled by
    the router/regenerate(), never by this function.
    """
    priors = await _historical_unit_cost(db, event.org_id)
    cap = getattr(plan, "stated_cap", None)  # ReservationPlan carries no cap field yet

    drafted = await agent.draft_lines(
        event, plan.unowned_items, priors, cap, db=db, org_id=event.org_id
    )

    # Never trust a total from the model — every number below is Python Decimal math.
    line_totals = [headroom.line_total(d.unit_cost, d.quantity) for d in drafted]
    subtotal = headroom.subtotal(line_totals)
    estimated_total = headroom.estimated_total(subtotal)

    budget_row = await _current_budget(db, event.org_id)
    if budget_row is None:
        raise NoSemesterBudget(f"org {event.org_id} has no budgets row to draft against")

    event_budget = EventBudget(
        event_id=event.id,
        budget_id=budget_row.id,
        estimated_total=estimated_total,
        actual_total=Decimal("0.00"),
        stated_cap=cap,
        status="draft",
    )
    db.add(event_budget)
    await db.flush()  # assign event_budget.id for the line-item FKs — no commit

    for d, total in zip(drafted, line_totals):
        db.add(
            BudgetLineItem(
                event_budget_id=event_budget.id,
                category=d.category,
                description=d.description,
                unit_cost=d.unit_cost,
                quantity=d.quantity,
                line_total=total,
                source="ai",
            )
        )
    await db.flush()

    return BudgetDraft(
        event_budget_id=event_budget.id,
        estimated_total=estimated_total,
        stated_cap=cap,
        verdict="draft",  # headroom is checked by the caller (see get_headroom/regenerate) —
                          # draft_for_event's own contract has no verdict field to fill from
                          # a live check without also computing committed/actual here, which
                          # would duplicate work the caller (scheduling) already needs anyway.
    )


async def approve(db: AsyncSession, budget_id: UUID, actor_id: UUID) -> EventBudget:
    """Approve a draft budget, committing it against the semester allocation. Unlike
    draft_for_event, this entry point owns its own transaction.

    `actor_id` is accepted for an eventual approval audit trail — schema.sql has no
    `approved_by` column yet, so it isn't persisted. Flag for a future migration if
    that's needed.
    """
    event_budget = await db.get(EventBudget, budget_id)
    if event_budget is None:
        raise LookupError(f"event_budget {budget_id} not found")
    if event_budget.status != "draft":
        raise InvalidBudgetStatus(
            f"event_budget {budget_id} is '{event_budget.status}', expected 'draft'"
        )
    event_budget.status = "approved"
    await db.commit()
    await db.refresh(event_budget)
    return event_budget


async def _match_line_item(db: AsyncSession, event_budget_id: UUID, description: str) -> UUID | None:
    """Best-effort match: closest unmatched budget_line_item by description/category
    similarity. Returns None rather than guessing when nothing clears the threshold —
    an unmatched expense is a normal, reconcilable outcome; a wrong match would
    silently corrupt the itemized budget."""
    candidates = (
        await db.execute(
            select(BudgetLineItem).where(BudgetLineItem.event_budget_id == event_budget_id)
        )
    ).scalars().all()
    if not candidates:
        return None

    already_matched = set(
        (
            await db.execute(
                select(Expense.line_item_id).where(
                    Expense.event_budget_id == event_budget_id,
                    Expense.line_item_id.is_not(None),
                )
            )
        ).scalars()
    )
    unmatched = [c for c in candidates if c.id not in already_matched]
    if not unmatched:
        return None

    needle = description.lower()
    best, best_score = None, 0.0
    for c in unmatched:
        haystack = f"{c.category} {c.description or ''}".lower()
        score = difflib.SequenceMatcher(None, needle, haystack).ratio()
        if c.category.lower() in needle:  # cheap boost when the category is named explicitly
            score += 0.15
        if score > best_score:
            best, best_score = c, score

    return best.id if best is not None and best_score >= _MATCH_THRESHOLD else None


async def log_expense(
    db: AsyncSession, budget_id: UUID, amount: Decimal, description: str, member_id: UUID
) -> Expense:
    """Log an actual expense against a budget, best-effort matched to a line item.
    Owns its own transaction — commits on success."""
    event_budget = await db.get(EventBudget, budget_id)
    if event_budget is None:
        raise LookupError(f"event_budget {budget_id} not found")

    line_item_id = await _match_line_item(db, event_budget.id, description)
    matched_line = await db.get(BudgetLineItem, line_item_id) if line_item_id else None

    expense = Expense(
        event_budget_id=event_budget.id,
        line_item_id=line_item_id,
        paid_by=member_id,
        amount=amount,
        description=description,
        status="pending",
        spent_at=now_utc(),
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)

    # Transient — not a mapped column, just convenient for the immediate response.
    # schemas.ExpenseOut declares a `variance` field that picks this up via
    # model_validate(expense, from_attributes=True).
    expense.variance = (amount - matched_line.line_total) if matched_line is not None else None
    return expense


# ---------------------------------------------------------------------------
# Supporting reads/writes for router.py — none of these are scheduling's contract,
# so they're free to have whatever shape is convenient.
# ---------------------------------------------------------------------------


async def get_lines(db: AsyncSession, event_budget_id: UUID) -> list[BudgetLineItem]:
    return (
        await db.execute(
            select(BudgetLineItem)
            .where(BudgetLineItem.event_budget_id == event_budget_id)
            .order_by(BudgetLineItem.line_total.desc())
        )
    ).scalars().all()


async def list_event_budgets(db: AsyncSession, org_id: UUID) -> list[dict]:
    """(event_budget id, event title, status, estimated_total) for the org — backs the
    bot's budget picker (autocomplete for /budget approve and /expense)."""
    rows = await db.execute(
        text(
            "SELECT eb.id, e.title, eb.status, eb.estimated_total "
            "FROM event_budgets eb JOIN events e ON e.id = eb.event_id "
            "WHERE e.org_id = :o ORDER BY e.start_utc DESC"
        ),
        {"o": org_id},
    )
    return [dict(r) for r in rows.mappings().all()]


async def get_event_budget(
    db: AsyncSession, event_id: UUID
) -> tuple[EventBudget, list[BudgetLineItem]] | None:
    """Most recent event_budget for this event, with its lines."""
    eb = (
        await db.execute(
            select(EventBudget)
            .where(EventBudget.event_id == event_id)
            .order_by(EventBudget.created_at.desc())
        )
    ).scalars().first()
    if eb is None:
        return None
    return eb, await get_lines(db, eb.id)


class RegeneratedDraft:
    """Local return shape for regenerate() — deliberately NOT app.core.types.BudgetDraft,
    which is scheduling's contract and must stay exactly 4 fields."""

    def __init__(self, event_budget, lines, verdict, remaining, suggested_cuts):
        self.event_budget = event_budget
        self.lines = lines
        self.verdict = verdict
        self.remaining = remaining
        self.suggested_cuts = suggested_cuts


async def regenerate(db: AsyncSession, event_id: UUID) -> RegeneratedDraft:
    """Re-draft an event's budget on demand (outside scheduling's confirm
    transaction). Owns its own commit.

    Limitation: finance has no way to re-fetch the live resources plan after the
    fact without importing resources/scheduling, which the import-direction rule
    forbids. It reuses the previous draft's equipment_rental lines as the
    "unowned items" list and re-prices everything against current priors.
    """
    row = (
        await db.execute(
            text(
                "SELECT id, org_id, title, start_utc, end_utc, expected_attendance "
                "FROM events WHERE id = :id"
            ),
            {"id": event_id},
        )
    ).mappings().first()
    if row is None:
        raise LookupError(f"event {event_id} not found")

    previous = await get_event_budget(db, event_id)
    unowned: list[UnownedItem] = []
    cap: Decimal | None = None
    if previous is not None:
        old_eb, old_lines = previous
        cap = old_eb.stated_cap
        unowned = [
            UnownedItem(item_name=l.description or l.category, quantity=l.quantity, est_cost=l.unit_cost)
            for l in old_lines
            if l.category == "equipment_rental"
        ]
        if old_eb.status in ("draft", "approved", "reconciling"):
            # Supersede any live budget (not just drafts) so its estimated_total stops
            # counting toward `committed` — i.e. the previous allocation is released.
            old_eb.status = "cancelled"

    event = EventView(
        id=row["id"],
        org_id=row["org_id"],
        title=row["title"],
        start_utc=row["start_utc"],
        end_utc=row["end_utc"],
        expected_attendance=row["expected_attendance"],
    )
    plan = ReservationPlan(event_id=row["id"], unowned_items=unowned)
    if cap is not None:
        plan.stated_cap = cap  # type: ignore[attr-defined] — ReservationPlan has no cap field yet

    await draft_for_event(db, event, plan)
    new_eb, new_lines = await get_event_budget(db, event_id)

    # Carry the event's real expenses onto the fresh budget and re-match them to the new
    # line items, so `actual` and the Estimate-vs-Actual report follow the regenerated
    # plan rather than the superseded one.
    if previous is not None:
        moved = (
            await db.execute(select(Expense).where(Expense.event_budget_id == previous[0].id))
        ).scalars().all()
        for ex in moved:
            ex.event_budget_id = new_eb.id
            ex.line_item_id = await _match_line_item(db, new_eb.id, ex.description or "")

    budget_row = await db.get(Budget, new_eb.budget_id)
    committed, actual = await _committed_and_actual(db, budget_row.id)
    result = headroom.check(budget_row.total_allocated, committed, actual, new_eb.estimated_total)

    suggested_cuts: list[str] | None = None
    if result.verdict == "OVER":
        drafted_for_agent = [
            agent.DraftedLine(
                category=l.category, description=l.description or "", unit_cost=l.unit_cost, quantity=l.quantity
            )
            for l in new_lines
        ]
        cuts = await agent.suggest_cuts(drafted_for_agent, -result.after, db=db, org_id=event.org_id)
        suggested_cuts = [
            f"{c.description} ({c.category}): save ~${c.estimated_savings} — {c.rationale}" for c in cuts
        ]

    await db.commit()
    await db.refresh(new_eb)
    return RegeneratedDraft(new_eb, new_lines, result.verdict, result.after, suggested_cuts)

async def get_verdict(db: AsyncSession, event_budget: EventBudget) -> headroom.Headroom:
    """Live headroom check for an existing event_budget, without re-drafting.
    Used by the /budget draft bot command's cached-read path (an already-drafted
    budget has no stored verdict — draft_for_event doesn't compute one by design;
    see the note on that function)."""
    budget_row = await db.get(Budget, event_budget.budget_id)
    committed, actual = await _committed_and_actual(db, budget_row.id)
    return headroom.check(budget_row.total_allocated, committed, actual, event_budget.estimated_total)

async def patch_line_item(
    db: AsyncSession, budget_id: UUID, line_id: UUID, fields: dict
) -> BudgetLineItem:
    """Apply only the fields present in `fields` (router passes model_dump(exclude_unset=True)).
    Recomputes this line's total and the parent event_budget's estimated_total —
    never trusts a client-supplied total. Owns its own transaction."""
    line = await db.get(BudgetLineItem, line_id)
    if line is None or line.event_budget_id != budget_id:
        raise LookupError(f"line item {line_id} not found under budget {budget_id}")

    if "unit_cost" in fields:
        line.unit_cost = fields["unit_cost"]
    if "quantity" in fields:
        line.quantity = fields["quantity"]
    if "description" in fields:
        line.description = fields["description"]
    line.line_total = headroom.line_total(line.unit_cost, line.quantity)

    event_budget = await db.get(EventBudget, budget_id)
    siblings = await get_lines(db, budget_id)
    sub = headroom.subtotal([l.line_total for l in siblings])
    event_budget.estimated_total = headroom.estimated_total(sub)

    await db.commit()
    await db.refresh(line)
    return line


async def get_headroom(
    db: AsyncSession, org_id: UUID, semester: str
) -> tuple[Budget, Decimal, Decimal, "headroom.Headroom"]:
    budget_row = (
        await db.execute(
            select(Budget).where(Budget.org_id == org_id, Budget.semester == semester)
        )
    ).scalars().first()
    if budget_row is None:
        raise LookupError(f"no budget for org {org_id} semester {semester!r}")
    committed, actual = await _committed_and_actual(db, budget_row.id)
    result = headroom.check(budget_row.total_allocated, committed, actual, Decimal("0.00"))
    return budget_row, committed, actual, result


async def get_burndown(db: AsyncSession, org_id: UUID, semester: str):
    """Cumulative committed (approved event_budgets, by creation date) and actual
    (reimbursed/approved expenses, by spent_at) over the semester."""
    budget_row = (
        await db.execute(
            select(Budget).where(Budget.org_id == org_id, Budget.semester == semester)
        )
    ).scalars().first()
    if budget_row is None:
        raise LookupError(f"no budget for org {org_id} semester {semester!r}")

    committed_rows = (
        await db.execute(
            select(
                cast(EventBudget.created_at, Date).label("d"),
                EventBudget.estimated_total.label("amt"),
            )
            .where(EventBudget.budget_id == budget_row.id, EventBudget.status == "approved")
            .order_by(EventBudget.created_at)
        )
    ).all()
    _spent_day = cast(func.coalesce(Expense.spent_at, Expense.created_at), Date)
    actual_rows = (
        await db.execute(
            select(_spent_day.label("d"), Expense.amount.label("amt"))
            .join(EventBudget, EventBudget.id == Expense.event_budget_id)
            .where(
                EventBudget.budget_id == budget_row.id,
                Expense.status.in_(("approved", "reimbursed")),
            )
            .order_by(_spent_day)
        )
    ).all()

    dates = sorted({r.d for r in committed_rows} | {r.d for r in actual_rows})
    points = []
    running_committed = running_actual = Decimal("0.00")
    ci = ai = 0
    for d in dates:
        while ci < len(committed_rows) and committed_rows[ci].d == d:
            running_committed += committed_rows[ci].amt
            ci += 1
        while ai < len(actual_rows) and actual_rows[ai].d == d:
            running_actual += actual_rows[ai].amt
            ai += 1
        points.append((d, running_committed, running_actual))
    return budget_row, points


async def get_variance(db: AsyncSession, org_id: UUID):
    """Estimated vs. actual per matched (expense, line_item) pair, across every
    budget this org has ever had."""
    rows = (
        await db.execute(
            text(
                """
                SELECT e.title AS event_title, bli.category AS category,
                       bli.description AS description, bli.line_total AS estimated,
                       ex.amount AS actual
                FROM expenses ex
                JOIN budget_line_items bli ON bli.id = ex.line_item_id
                JOIN event_budgets eb ON eb.id = ex.event_budget_id
                JOIN events e ON e.id = eb.event_id
                JOIN budgets b ON b.id = eb.budget_id
                WHERE b.org_id = :org_id AND ex.status IN ('approved', 'reimbursed')
                ORDER BY e.title, bli.category
                """
            ),
            {"org_id": org_id},
        )
    ).mappings().all()
    return rows