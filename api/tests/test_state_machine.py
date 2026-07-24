"""Reservation state machine — pure, no DB. _transition() only mutates an in-memory
ORM object's .status attribute; nothing here needs a session."""

import pytest

from app.features.resources.service import (
    InvalidTransitionError,
    ReservationStatus,
    _transition,
)
from app.models.resources import ResourceReservation


def _reservation(status: str) -> ResourceReservation:
    return ResourceReservation(status=status, quantity=1, exclusive=False)


@pytest.mark.parametrize(
    "start,target",
    [
        ("held", ReservationStatus.CONFIRMED),
        ("held", ReservationStatus.RELEASED),
        ("confirmed", ReservationStatus.CHECKED_OUT),
        ("confirmed", ReservationStatus.RELEASED),
        ("checked_out", ReservationStatus.RETURNED),
        ("checked_out", ReservationStatus.OVERDUE),
        ("overdue", ReservationStatus.RETURNED),
    ],
)
def test_allowed_transitions(start, target):
    reservation = _reservation(start)
    _transition(reservation, target)
    assert reservation.status == target.value


@pytest.mark.parametrize(
    "start,target",
    [
        ("held", ReservationStatus.CHECKED_OUT),  # must go through confirmed first
        ("released", ReservationStatus.CONFIRMED),  # terminal
        ("returned", ReservationStatus.HELD),  # terminal
        ("confirmed", ReservationStatus.OVERDUE),  # must be checked out first
        ("overdue", ReservationStatus.CHECKED_OUT),  # can't go backwards
    ],
)
def test_rejected_transitions(start, target):
    reservation = _reservation(start)
    with pytest.raises(InvalidTransitionError):
        _transition(reservation, target)
    # rejection must not mutate state
    assert reservation.status == start
