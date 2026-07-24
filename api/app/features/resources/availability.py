"""Pure availability math (Member B). No I/O, no LLM — unit-tested. This is the
defensible logic CLAUDE.md points to: "scoring/availability/headroom are pure functions."

One query decides everything: total capacity minus what's already reserved in the
requested window, compared against what this event needs.
"""

from dataclasses import dataclass
from enum import Enum


class AvailabilityStatus(str, Enum):
    OK = "OK"  # fully available
    PARTIAL = "PARTIAL"  # some available, not all — reserve the portion, flag the rest
    CONFLICT = "CONFLICT"  # nothing available


@dataclass(frozen=True)
class AvailabilityResult:
    status: AvailabilityStatus
    available: int  # how much can actually be reserved right now (0 on CONFLICT)
    shortfall: int  # requested - available (0 on OK)


def compute(total: int, reserved: int, requested: int) -> AvailabilityResult:
    """total = resource.quantity_total; reserved = sum of overlapping held/confirmed/
    checked_out reservations in the requested window; requested = what this event needs."""
    if total < 0 or reserved < 0 or requested < 0:
        raise ValueError("quantities must be non-negative")

    free = max(total - reserved, 0)

    if free >= requested:
        return AvailabilityResult(AvailabilityStatus.OK, available=requested, shortfall=0)
    if free > 0:
        return AvailabilityResult(AvailabilityStatus.PARTIAL, available=free, shortfall=requested - free)
    return AvailabilityResult(AvailabilityStatus.CONFLICT, available=0, shortfall=requested)
