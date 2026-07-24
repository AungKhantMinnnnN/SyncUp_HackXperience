"""Finance service (Member C). Never imports scheduling. Never commits — the caller
owns the transaction. Money is Decimal everywhere. Add headroom.py (pure), agent.py.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import BudgetDraft, EventView, ReservationPlan


async def draft_for_event(
    db: AsyncSession, event: EventView, plan: ReservationPlan
) -> BudgetDraft:
    """Draft an itemized budget (status=draft), check it against the semester
    allocation and stated cap. Uses the passed session; must not commit."""
    raise NotImplementedError  # Member C
