"""Resources service (Member B). Never imports scheduling. Never commits — the caller
(scheduling) owns the transaction. Add availability.py (pure), agent.py, router.py.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.types import EventView, ReservationPlan


async def plan_for_event(db: AsyncSession, event: EventView) -> ReservationPlan:
    """Infer packing list, reserve equipment (status=held), flag conflicts.
    Uses the passed session; must not commit.

    ponytail: Member B stub — no DB writes yet, returns an empty plan so the confirm
    transaction runs end to end. The real version holds equipment on `db` (never
    commits); the surrounding `db.begin()` in scheduling already makes it atomic.
    """
    return ReservationPlan(event_id=event.id)


async def confirm_for_event(db: AsyncSession, event_id: UUID) -> None:
    """Flip held reservations to confirmed for an approved event."""
    raise NotImplementedError  # Member B
