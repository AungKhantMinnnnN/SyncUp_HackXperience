"""Scheduling service (Member A). Owns the confirm transaction — the heart of the app.

Import direction: scheduling MAY import resources + finance. They must never import us.
Add router.py, schemas.py, scoring.py (pure), agent.py alongside as the feature grows.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.finance import service as finance_service
from app.features.resources import service as resources_service


async def confirm_proposal(db: AsyncSession, proposal_id: UUID, actor_id: UUID):
    """One transaction across all three modules. Any exception rolls back everything.

    async with db.begin():
        event  = await _create_event(db, proposal, actor_id)
        await _add_attendees(db, event, proposal)
        plan   = await resources_service.plan_for_event(db, event)
        budget = await finance_service.draft_for_event(db, event, plan)
    return EventPlan(event=event, reservations=plan, budget=budget)
    """
    raise NotImplementedError  # Member A
