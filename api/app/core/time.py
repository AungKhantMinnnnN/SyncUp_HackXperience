"""UTC + interval overlap utilities. The one conflict primitive lives here."""

from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open interval overlap [start, end). Touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


if __name__ == "__main__":
    from datetime import timedelta

    t = now_utc()
    assert overlaps(t, t + timedelta(hours=2), t + timedelta(hours=1), t + timedelta(hours=3))
    assert not overlaps(t, t + timedelta(hours=1), t + timedelta(hours=1), t + timedelta(hours=2))
    print("ok")
