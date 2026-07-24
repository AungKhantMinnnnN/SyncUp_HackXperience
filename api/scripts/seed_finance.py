# api/scripts/seed_finance.py
"""Idempotent finance demo-data seeder.

Seeds one semester budget, 4 past (closed) event_budgets with 3-5 line items each
spread across food/venue/equipment_rental/printing/materials, plus a matching
reimbursed expense per line item (amount intentionally off the estimate, over and
under, so variance reporting has something to show).

Run (from api/):
    python -m scripts.seed_finance
    python -m scripts.seed_finance --org-id 11111111-1111-1111-1111-111111111111

Safe to re-run: if a budgets row already exists for the resolved org_id + semester,
the script prints a message and exits without writing anything.

Note: `scripts/` needs to be importable as a package for `-m` to work — either run
from the `api/` directory (implicit namespace package) or add `scripts/__init__.py`.
"""

import argparse
import asyncio
import random
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from app.core.time import now_utc
from app.db import SessionLocal

SEMESTER = "Fall2026"
TOTAL_ALLOCATED = Decimal("2500.00")
NUM_EVENTS = 4

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class LineSpec:
    category: str
    description: str
    unit_cost: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return (self.unit_cost * self.quantity).quantize(TWO_PLACES)


def _money(rng: random.Random, lo: float, hi: float) -> Decimal:
    return Decimal(str(round(rng.uniform(lo, hi), 2)))


def _build_lines(rng: random.Random, attendance: int) -> list[LineSpec]:
    """3-5 line items, categories vary per event so the price-prior history looks real."""
    pool = [
        LineSpec("food", "Catering — pizza & drinks",
                 unit_cost=_money(rng, 4.0, 6.0), quantity=max(attendance, 1)),
        LineSpec("venue", "Room hire & cleaning fee",
                 unit_cost=_money(rng, 40.0, 120.0), quantity=1),
        LineSpec("equipment_rental", "AV rental (mic/speaker)",
                 unit_cost=_money(rng, 15.0, 45.0), quantity=rng.choice([1, 2])),
        LineSpec("printing", "Posters & sign-in sheets",
                 unit_cost=_money(rng, 0.15, 0.45), quantity=rng.randint(60, 150)),
        LineSpec("materials", "Decorations & supplies",
                 unit_cost=_money(rng, 5.0, 25.0), quantity=rng.randint(2, 8)),
    ]
    count = rng.randint(3, 5)
    # food first if selected, so it's always attendance-anchored line #1 when present
    chosen = rng.sample(pool, count)
    chosen.sort(key=lambda l: 0 if l.category == "food" else 1)
    return chosen


async def _resolve_org_id(session, cli_org_id: UUID | None) -> UUID:
    if cli_org_id:
        return cli_org_id
    row = (
        await session.execute(text("SELECT id FROM organizations ORDER BY created_at LIMIT 1"))
    ).first()
    if row is None:
        raise SystemExit(
            "No organizations found. Run `python scripts/seed.py` first, "
            "or pass --org-id explicitly."
        )
    return row.id


async def _get_or_create_events(session, org_id: UUID, rng: random.Random, count: int):
    """Prefer real events (created by scripts/seed.py); fall back to minimal
    placeholder rows only if none exist, since event_budgets.event_id is NOT NULL."""
    rows = list(
        (
            await session.execute(
                text(
                    "SELECT id, expected_attendance FROM events "
                    "WHERE org_id = :org_id ORDER BY start_utc"
                ),
                {"org_id": org_id},
            )
        ).all()
    )
    if rows:
        # Cycle through whatever exists if fewer than `count`.
        return [rows[i % len(rows)] for i in range(count)]

    print("  no existing events found for this org — creating placeholder past events")
    base = now_utc() - timedelta(days=30)
    created = []
    for i in range(count):
        start = base - timedelta(weeks=count - i)
        res = await session.execute(
            text(
                """
                INSERT INTO events (org_id, title, start_utc, end_utc, expected_attendance, status)
                VALUES (:org_id, :title, :start, :end, :attendance, 'completed')
                RETURNING id, expected_attendance
                """
            ),
            {
                "org_id": org_id,
                "title": f"Past event #{i + 1}",
                "start": start,
                "end": start + timedelta(hours=2),
                "attendance": rng.randint(20, 100),
            },
        )
        created.append(res.first())
    return created


async def seed_finance(org_id_arg: UUID | None) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            org_id = await _resolve_org_id(session, org_id_arg)

            existing = (
                await session.execute(
                    text("SELECT id FROM budgets WHERE org_id = :org_id AND semester = :sem"),
                    {"org_id": org_id, "sem": SEMESTER},
                )
            ).first()
            if existing is not None:
                print(
                    f"seed_finance: budget already exists for org={org_id} "
                    f"semester={SEMESTER} (budget_id={existing.id}) — skipping."
                )
                return

            rng = random.Random(f"finance-seed-{org_id}")  # deterministic per org

            budget_id = (
                await session.execute(
                    text(
                        """
                        INSERT INTO budgets (org_id, semester, total_allocated, currency)
                        VALUES (:org_id, :sem, :total, 'USD')
                        RETURNING id
                        """
                    ),
                    {"org_id": org_id, "sem": SEMESTER, "total": TOTAL_ALLOCATED},
                )
            ).scalar_one()

            events = await _get_or_create_events(session, org_id, rng, NUM_EVENTS)

            events_seeded = lines_seeded = expenses_seeded = 0
            spent_anchor = now_utc() - timedelta(days=10)

            for idx, ev in enumerate(events):
                attendance = ev.expected_attendance or rng.randint(30, 100)
                lines = _build_lines(rng, attendance)
                subtotal = sum((l.line_total for l in lines), Decimal("0.00"))
                contingency = (subtotal * Decimal("0.10")).quantize(TWO_PLACES)
                estimated_total = subtotal + contingency

                event_budget_id = (
                    await session.execute(
                        text(
                            """
                            INSERT INTO event_budgets
                                (event_id, budget_id, estimated_total, actual_total, stated_cap, status)
                            VALUES (:event_id, :budget_id, :estimated, 0.00, NULL, 'closed')
                            RETURNING id
                            """
                        ),
                        {"event_id": ev.id, "budget_id": budget_id, "estimated": estimated_total},
                    )
                ).scalar_one()

                actual_total = Decimal("0.00")
                for l in lines:
                    line_item_id = (
                        await session.execute(
                            text(
                                """
                                INSERT INTO budget_line_items
                                    (event_budget_id, category, description, unit_cost, quantity, line_total, source)
                                VALUES (:ebid, :cat, :desc, :unit_cost, :qty, :total, 'seed')
                                RETURNING id
                                """
                            ),
                            {
                                "ebid": event_budget_id,
                                "cat": l.category,
                                "desc": l.description,
                                "unit_cost": l.unit_cost,
                                "qty": l.quantity,
                                "total": l.line_total,
                            },
                        )
                    ).scalar_one()
                    lines_seeded += 1

                    # ±15% of estimate, so some events ran over and some under.
                    factor = Decimal(str(round(rng.uniform(0.85, 1.15), 3)))
                    amount = (l.line_total * factor).quantize(TWO_PLACES)
                    actual_total += amount
                    spent_at = spent_anchor - timedelta(weeks=4 * (len(events) - idx))

                    await session.execute(
                        text(
                            """
                            INSERT INTO expenses
                                (event_budget_id, line_item_id, amount, description, status, spent_at)
                            VALUES (:ebid, :lid, :amount, :desc, 'reimbursed', :spent_at)
                            """
                        ),
                        {
                            "ebid": event_budget_id,
                            "lid": line_item_id,
                            "amount": amount,
                            "desc": f"Receipt — {l.description}",
                            "spent_at": spent_at,
                        },
                    )
                    expenses_seeded += 1

                await session.execute(
                    text("UPDATE event_budgets SET actual_total = :actual WHERE id = :id"),
                    {"actual": actual_total, "id": event_budget_id},
                )
                events_seeded += 1

        # COMMIT happened on exiting `session.begin()` above.
        print("\nseed_finance: done")
        print(f"{'budget_id':<18} {budget_id}")
        print(f"{'org_id':<18} {org_id}")
        print(f"{'semester':<18} {SEMESTER}")
        print(f"{'total_allocated':<18} {TOTAL_ALLOCATED}")
        print(f"{'events seeded':<18} {events_seeded}")
        print(f"{'line items':<18} {lines_seeded}")
        print(f"{'expenses':<18} {expenses_seeded}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Seed finance demo data: budgets, event_budgets, budget_line_items, expenses."
    )
    p.add_argument(
        "--org-id",
        type=str,
        default=None,
        help="Organization UUID to seed for. Defaults to the first row in `organizations`.",
    )
    return p.parse_args()


async def main() -> None:
    args = _parse_args()
    org_id = UUID(args.org_id) if args.org_id else None
    await seed_finance(org_id)


if __name__ == "__main__":
    asyncio.run(main())