"""Finance service (Member C). Never imports scheduling. Never commits — the caller
owns the transaction. Money is Decimal everywhere. Add headroom.py (pure), agent.py.
"""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import BudgetDraft, EventView, ReservationPlan


async def draft_for_event(
    db: AsyncSession, event: EventView, plan: ReservationPlan
) -> BudgetDraft:
    """Draft an itemized budget (status=draft), check it against the semester
    allocation and stated cap. Uses the passed session; must not commit.

    ponytail: Member C stub — no DB writes yet, returns a zero draft so the confirm
    transaction runs end to end. The real version writes line items on `db` (never
    commits) and computes the verdict from the semester allocation.
    """
    return BudgetDraft(
        event_budget_id=uuid4(),
        estimated_total=Decimal("0.00"),
        stated_cap=None,
        verdict="within_cap",
    )
