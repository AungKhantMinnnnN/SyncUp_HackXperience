"""Pure slot scoring (doc §4). The LLM parses and explains; it never scores — this
is what makes the module demo-reliable and defensible to judges.

Rules: no imports from app.db, app.models, or app.core.llm. Plain data in, plain data
out, trivially testable. Reuses the one conflict primitive (app.core.time.overlaps).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.time import overlaps

# --- scoring reference (doc §4 table) -------------------------------------------------
HARD_KINDS = frozenset({"exam", "class"})  # required member with these => slot eliminated
GRANULARITY = timedelta(minutes=30)
DEDUPE_BUCKET = timedelta(hours=3)
PENALTY_EXAM_48H = 25  # slot within 48h of an exam
PENALTY_LATE_NIGHT = 15  # start >= 21:00
PENALTY_BACK_TO_BACK = 10  # < 30 min gap from another org event
PENALTY_FAIRNESS = 5  # per member who missed >= 2 of last 5 events
LATE_NIGHT_HOUR = 21
BACK_TO_BACK_GAP = timedelta(minutes=30)
EXAM_PROXIMITY = timedelta(hours=48)


@dataclass(frozen=True)
class Constraints:
    duration_minutes: int
    window_start: datetime
    window_end: datetime
    must_be_before: datetime | None = None


@dataclass(frozen=True)
class MemberView:
    id: UUID
    weight: int
    required: bool


@dataclass(frozen=True)
class BusyInterval:
    member_id: UUID
    kind: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime


@dataclass
class ScoredSlot:
    start: datetime
    end: datetime
    score: float
    attendance_pct: float  # 0-100
    free_member_ids: list[UUID] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def _localize(dt: datetime, tz: str | None) -> datetime:
    """UTC (or naive-as-UTC) -> org-local wall clock. Quiet hours and late-night are
    org-local rules; busy_blocks are stored UTC."""
    if tz is None:
        return dt
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(tz))


def _in_quiet_hours(local_time: time, quiet: tuple[time, time] | None) -> bool:
    if quiet is None:
        return False
    lo, hi = quiet
    return (lo <= local_time or local_time < hi) if lo > hi else (lo <= local_time < hi)


def _candidate_starts(c: Constraints) -> list[datetime]:
    dur = timedelta(minutes=c.duration_minutes)
    out, t = [], c.window_start
    while t + dur <= c.window_end:
        if c.must_be_before is None or t + dur <= c.must_be_before:
            out.append(t)
        t += GRANULARITY
    return out


def score_slots(
    constraints: Constraints,
    members: Sequence[MemberView],
    busy: Sequence[BusyInterval],
    existing_events: Sequence[Interval] = (),
    fairness: Mapping[UUID, int] | None = None,
    quiet_hours: tuple[time, time] | None = None,  # optional; doc §4 discards slots here
    tz: str | None = None,  # org timezone; localizes quiet-hours + late-night checks
) -> list[ScoredSlot]:
    fairness = fairness or {}
    dur = timedelta(minutes=constraints.duration_minutes)
    by_member: dict[UUID, list[BusyInterval]] = {}
    for b in busy:
        by_member.setdefault(b.member_id, []).append(b)

    required = [m for m in members if m.required] or list(members)  # none marked => all required
    total_weight = sum(m.weight for m in required) or 1

    scored: list[ScoredSlot] = []
    for start in _candidate_starts(constraints):
        end = start + dur
        local_start = _localize(start, tz)
        if _in_quiet_hours(local_start.time(), quiet_hours):
            continue

        # Hard conflict: any required member with an exam/class overlap eliminates the slot.
        if any(
            b.kind in HARD_KINDS and overlaps(start, end, b.start, b.end)
            for m in required
            for b in by_member.get(m.id, ())
        ):
            continue

        free = [
            m for m in required
            if not any(overlaps(start, end, b.start, b.end) for b in by_member.get(m.id, ()))
        ]
        frac = sum(m.weight for m in free) / total_weight

        penalty, conflicts = 0, []
        busy_count = len(required) - len(free)
        if busy_count:
            conflicts.append(f"{busy_count} member(s) busy")

        near_exam = any(
            b.kind == "exam" and abs(b.start - start) <= EXAM_PROXIMITY
            for m in required
            for b in by_member.get(m.id, ())
        )
        if near_exam:
            penalty += PENALTY_EXAM_48H
            conflicts.append("within 48h of an exam")
        if local_start.hour >= LATE_NIGHT_HOUR:
            penalty += PENALTY_LATE_NIGHT
            conflicts.append("late night")
        if any(
            abs(start - ev.end) < BACK_TO_BACK_GAP or abs(ev.start - end) < BACK_TO_BACK_GAP
            for ev in existing_events
        ):
            penalty += PENALTY_BACK_TO_BACK
            conflicts.append("back-to-back with another event")
        debt = sum(1 for m in required if fairness.get(m.id, 0) >= 2)
        if debt:
            penalty += PENALTY_FAIRNESS * debt
            conflicts.append(f"fairness debt ({debt})")

        scored.append(
            ScoredSlot(
                start=start,
                end=end,
                score=round(frac * 100 - penalty, 2),
                attendance_pct=round(frac * 100, 2),
                free_member_ids=[m.id for m in free],
                conflicts=conflicts,
            )
        )

    return _top_per_bucket(scored, constraints.window_start)


def _top_per_bucket(slots: list[ScoredSlot], origin: datetime, limit: int = 5) -> list[ScoredSlot]:
    """Deduplicate overlaps — keep the best slot per 3-hour bucket, then top `limit`."""
    best: dict[int, ScoredSlot] = {}
    for s in slots:
        bucket = int((s.start - origin) / DEDUPE_BUCKET)
        if bucket not in best or s.score > best[bucket].score:
            best[bucket] = s
    ranked = sorted(best.values(), key=lambda s: s.score, reverse=True)
    return ranked[:limit]


if __name__ == "__main__":
    # ponytail: smoke check, not a test suite — proves elimination + ranking run.
    from uuid import uuid4

    base = datetime(2026, 8, 3, 9, 0)  # a Monday 09:00
    a, b = uuid4(), uuid4()
    members = [MemberView(a, 3, True), MemberView(b, 1, True)]
    # `a` has a class 10:00-11:00 -> any slot overlapping it is eliminated (a is required).
    busy = [BusyInterval(a, "class", base + timedelta(hours=1), base + timedelta(hours=2))]
    c = Constraints(duration_minutes=60, window_start=base, window_end=base + timedelta(hours=6))
    out = score_slots(c, members, busy)
    assert out, "expected some slots"
    assert out[0].score == 100.0, out[0]  # a fully-free slot tops the ranking
    assert all(not (s.start < base + timedelta(hours=2) and base + timedelta(hours=1) < s.end)
            for s in out), "a slot overlapping the required member's class survived"
    print(f"ok: {len(out)} ranked slots, top score {out[0].score}")
