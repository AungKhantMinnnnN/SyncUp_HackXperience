"""Interval overlap — pure, no I/O. Not resources' own file (app/core/time.py is
shared), but it's the primitive availability.py's DB queries are built on, so it's
worth pinning down here explicitly."""

from datetime import timedelta

from app.core.time import now_utc, overlaps


def test_overlapping_intervals():
    t = now_utc()
    assert overlaps(t, t + timedelta(hours=2), t + timedelta(hours=1), t + timedelta(hours=3))


def test_adjacent_intervals_do_not_overlap():
    # half-open [start, end) — touching endpoints must not count as a conflict
    t = now_utc()
    assert not overlaps(t, t + timedelta(hours=1), t + timedelta(hours=1), t + timedelta(hours=2))


def test_identical_intervals_overlap():
    t = now_utc()
    assert overlaps(t, t + timedelta(hours=1), t, t + timedelta(hours=1))


def test_disjoint_intervals_do_not_overlap():
    t = now_utc()
    assert not overlaps(t, t + timedelta(hours=1), t + timedelta(hours=5), t + timedelta(hours=6))


def test_one_interval_fully_inside_another():
    t = now_utc()
    assert overlaps(t, t + timedelta(hours=4), t + timedelta(hours=1), t + timedelta(hours=2))
