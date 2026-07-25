"""Pure budget math — no I/O, no LLM. Unit-test with plain Decimals."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Sequence

MONEY = Decimal("0.01")
CONTINGENCY_RATE = Decimal("0.10")
TIGHT_BUFFER_RATE = Decimal("0.10")

Verdict = Literal["OK", "TIGHT", "OVER"]


def quantize_money(value: Decimal) -> Decimal:
    """Round to cents (matches NUMERIC(12,2) in Postgres)."""
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def line_total(unit_cost: Decimal, quantity: int) -> Decimal:
    """Single line: unit_cost × quantity."""
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    return quantize_money(unit_cost * Decimal(quantity))


def subtotal(line_totals: Sequence[Decimal]) -> Decimal:
    """Sum of line totals before contingency."""
    return quantize_money(sum(line_totals, start=Decimal("0")))


def contingency(subtotal_amount: Decimal, rate: Decimal = CONTINGENCY_RATE) -> Decimal:
    """Flat contingency (default 10% of subtotal)."""
    return quantize_money(subtotal_amount * rate)


def estimated_total(
    subtotal_amount: Decimal,
    rate: Decimal = CONTINGENCY_RATE,
) -> Decimal:
    """subtotal + contingency."""
    return quantize_money(subtotal_amount + contingency(subtotal_amount, rate))


def estimate_from_lines(
    lines: Sequence[tuple[Decimal, int]],
    rate: Decimal = CONTINGENCY_RATE,
) -> tuple[Decimal, Decimal, Decimal]:
    """Convenience: (subtotal, contingency, estimated_total) from (unit_cost, qty) pairs."""
    totals = [line_total(unit_cost, qty) for unit_cost, qty in lines]
    sub = subtotal(totals)
    cont = contingency(sub, rate)
    return sub, cont, estimated_total(sub, rate)


@dataclass(frozen=True, slots=True)
class Headroom:
    remaining: Decimal   # allocated - max(committed, actual)  (before this event)
    after: Decimal       # remaining - proposed
    verdict: Verdict


def check(
    allocated: Decimal,
    committed: Decimal,
    actual: Decimal,
    proposed: Decimal,
) -> Headroom:
    """Semester headroom verdict for a proposed event budget.

    remaining = allocated - max(committed, actual)
    after     = remaining - proposed

    `actual` (money spent) is money already inside `committed` (approved estimates), so
    the two must not both be subtracted — that would double-count spend. We take the
    larger, so overspend beyond the committed estimate still eats into headroom.

    OK    — after >= 0
    TIGHT — after < 0 but within 10% of allocated (warn, still allow)
    OVER  — worse than that (block approval)
    """
    remaining = quantize_money(allocated - max(committed, actual))
    after = quantize_money(remaining - proposed)

    if after >= Decimal("0"):
        verdict: Verdict = "OK"
    elif after >= quantize_money(-(allocated * TIGHT_BUFFER_RATE)):
        verdict = "TIGHT"
    else:
        verdict = "OVER"

    return Headroom(remaining=remaining, after=after, verdict=verdict)