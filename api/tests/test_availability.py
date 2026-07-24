import pytest

from app.features.resources.availability import AvailabilityStatus, compute


def test_fully_available():
    result = compute(total=120, reserved=0, requested=100)
    assert result.status is AvailabilityStatus.OK
    assert result.available == 100
    assert result.shortfall == 0


def test_exactly_enough_is_ok():
    result = compute(total=100, reserved=0, requested=100)
    assert result.status is AvailabilityStatus.OK


def test_partial_availability():
    # the projector-style shortage: 1 total, already 1 reserved elsewhere... use a
    # pooled example instead: 4 mics, 3 already reserved, event wants 2 -> 1 free
    result = compute(total=4, reserved=3, requested=2)
    assert result.status is AvailabilityStatus.PARTIAL
    assert result.available == 1
    assert result.shortfall == 1


def test_hard_conflict_when_nothing_free():
    result = compute(total=1, reserved=1, requested=1)
    assert result.status is AvailabilityStatus.CONFLICT
    assert result.available == 0
    assert result.shortfall == 1


def test_over_reserved_does_not_go_negative():
    # defensive: reserved should never exceed total, but don't let it produce a
    # negative "free" count if it somehow does
    result = compute(total=5, reserved=10, requested=1)
    assert result.status is AvailabilityStatus.CONFLICT
    assert result.available == 0


@pytest.mark.parametrize("total,reserved,requested", [(-1, 0, 1), (1, -1, 1), (1, 0, -1)])
def test_rejects_negative_quantities(total, reserved, requested):
    with pytest.raises(ValueError):
        compute(total, reserved, requested)
