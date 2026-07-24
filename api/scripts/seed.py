"""Idempotent dev seed — truncate then insert, so anyone can reset to a known
demo state in seconds. Targets in docs/04-Database-Schema.html section 8:
2 orgs, 12 members, ~150 busy_blocks, 4 venues, 15 resources (1 exclusive projector),
3 reservations incl. the Chess Club projector clash, 1 budget, 4 past event_budgets.

Run:  python scripts/seed.py   (against the DEV Supabase project only)
"""

import asyncio

from app.db import SessionLocal


async def seed() -> None:
    async with SessionLocal() as db:
        async with db.begin():
            # ponytail: fill in once the owned models land. Truncate-then-insert here.
            _ = db
    print("seed: not yet implemented")


if __name__ == "__main__":
    asyncio.run(seed())
