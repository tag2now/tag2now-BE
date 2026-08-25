"""Reservation state rules are pure — they need no database."""

from datetime import datetime, timedelta, timezone

import pytest

from reservation.domain import (
    MatchType, ReservationStatus, ensure_conditions_valid, ensure_joinable,
    ensure_participation_cancellable, status_for,
)
from reservation.exceptions import ReservationStateError

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(hours=1)
PAST = NOW - timedelta(hours=1)


def test_a_live_reservation_matches_once_participants_fill_capacity():
    assert status_for(0, 1) is ReservationStatus.OPEN
    assert status_for(1, 1) is ReservationStatus.MATCHED
    assert status_for(2, 3) is ReservationStatus.OPEN
    assert status_for(3, 3) is ReservationStatus.MATCHED


def test_an_open_future_reservation_with_room_is_joinable():
    ensure_joinable(ReservationStatus.OPEN, FUTURE, 0, 1, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.MATCHED, ReservationStatus.CANCELLED, ReservationStatus.ENDED])
def test_only_open_reservations_accept_participants(status):
    with pytest.raises(ReservationStateError, match="not open"):
        ensure_joinable(status, FUTURE, 0, 1, NOW)


def test_a_started_reservation_rejects_participants():
    with pytest.raises(ReservationStateError, match="not open"):
        ensure_joinable(ReservationStatus.OPEN, PAST, 0, 1, NOW)


def test_a_reservation_at_capacity_rejects_participants():
    with pytest.raises(ReservationStateError, match="full"):
        ensure_joinable(ReservationStatus.OPEN, FUTURE, 1, 1, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.OPEN, ReservationStatus.MATCHED])
def test_participation_in_a_live_future_reservation_is_cancellable(status):
    ensure_participation_cancellable(status, FUTURE, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.ENDED])
def test_participation_in_a_dead_reservation_is_not_cancellable(status):
    with pytest.raises(ReservationStateError, match="no longer active"):
        ensure_participation_cancellable(status, FUTURE, NOW)


def test_participation_in_a_started_reservation_is_not_cancellable():
    with pytest.raises(ReservationStateError, match="has started"):
        ensure_participation_cancellable(ReservationStatus.OPEN, PAST, NOW)


def test_a_rank_match_needs_ranks_and_a_capacity_of_one():
    ensure_conditions_valid(MatchType.RANK, ["Brawler"], 1)


def test_a_rank_match_without_ranks_is_rejected():
    with pytest.raises(ReservationStateError, match="require at least one rank"):
        ensure_conditions_valid(MatchType.RANK, [], 1)


@pytest.mark.parametrize("capacity", [2, 3])
def test_a_rank_match_beyond_one_participant_is_rejected(capacity):
    with pytest.raises(ReservationStateError, match="capacity of one"):
        ensure_conditions_valid(MatchType.RANK, ["Brawler"], capacity)


@pytest.mark.parametrize("capacity", [1, 2, 3])
def test_a_player_match_carries_no_ranks_at_any_capacity(capacity):
    ensure_conditions_valid(MatchType.PLAYER, [], capacity)


def test_a_player_match_with_ranks_is_rejected():
    with pytest.raises(ReservationStateError, match="do not use ranks"):
        ensure_conditions_valid(MatchType.PLAYER, ["Brawler"], 2)
