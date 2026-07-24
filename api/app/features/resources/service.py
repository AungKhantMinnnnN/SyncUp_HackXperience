"""Resources service (Member B). Never imports scheduling. Never commits — the caller
(scheduling) owns the transaction. Add availability.py (pure), agent.py, router.py.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import EventView, ReservationPlan


async def plan_for_event(db: AsyncSession, event: EventView) -> ReservationPlan:
    """Infer packing list, reserve equipment (status=held), flag conflicts.
    Uses the passed session; must not commit."""
    raise NotImplementedError  # Member B


async def confirm_for_event(db: AsyncSession, event_id: UUID) -> None:
    """Flip held reservations to confirmed for an approved event."""
    raise NotImplementedError  # Member B
