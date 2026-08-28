"""Reservation state rules are pure — they need no database."""

from datetime import datetime, time, timedelta, timezone

import pytest

from reservation.domain import (
    MatchType, ReservationStatus, ensure_conditions_valid, ensure_editable,
    ensure_joinable, ensure_participation_cancellable, start_at_from, status_for,
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
    with pytest.raises(ReservationStateError, match="참가할 수 없는"):
        ensure_joinable(status, FUTURE, 0, 1, NOW)


def test_a_started_reservation_rejects_participants():
    with pytest.raises(ReservationStateError, match="참가할 수 없는"):
        ensure_joinable(ReservationStatus.OPEN, PAST, 0, 1, NOW)


def test_a_reservation_at_capacity_rejects_participants():
    with pytest.raises(ReservationStateError, match="모집이 마감된"):
        ensure_joinable(ReservationStatus.OPEN, FUTURE, 1, 1, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.OPEN, ReservationStatus.MATCHED])
def test_participation_in_a_live_future_reservation_is_cancellable(status):
    ensure_participation_cancellable(status, FUTURE, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.ENDED])
def test_participation_in_a_dead_reservation_is_not_cancellable(status):
    with pytest.raises(ReservationStateError, match="취소되었거나 종료된"):
        ensure_participation_cancellable(status, FUTURE, NOW)


def test_participation_in_a_started_reservation_is_not_cancellable():
    with pytest.raises(ReservationStateError, match="이미 시작된"):
        ensure_participation_cancellable(ReservationStatus.OPEN, PAST, NOW)


def test_a_rank_match_needs_ranks_and_a_capacity_of_one():
    ensure_conditions_valid(MatchType.RANK, ["Brawler"], 1)


def test_a_rank_match_without_ranks_is_rejected():
    with pytest.raises(ReservationStateError, match="계급을 하나 이상"):
        ensure_conditions_valid(MatchType.RANK, [], 1)


@pytest.mark.parametrize("capacity", [2, 3])
def test_a_rank_match_beyond_one_participant_is_rejected(capacity):
    with pytest.raises(ReservationStateError, match="1명만 모집"):
        ensure_conditions_valid(MatchType.RANK, ["Brawler"], capacity)


@pytest.mark.parametrize("capacity", [1, 2, 3])
def test_a_player_match_carries_no_ranks_at_any_capacity(capacity):
    ensure_conditions_valid(MatchType.PLAYER, [], capacity)


def test_a_player_match_with_ranks_is_rejected():
    with pytest.raises(ReservationStateError, match="계급을 선택하지 않습니다"):
        ensure_conditions_valid(MatchType.PLAYER, ["Brawler"], 2)


def test_a_start_time_resolves_against_todays_date_in_seoul():
    # 10:00 UTC is 19:00 KST on the same day
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)

    start_at = start_at_from(time(21, 0), now)

    assert start_at == datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)  # 21:00 KST


def test_seoul_today_is_already_tomorrow_late_in_the_utc_day():
    # 16:00 UTC is 01:00 KST the next day, so "today" in Seoul is the 25th
    now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)

    start_at = start_at_from(time(21, 0), now)

    assert start_at == datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def test_the_result_keeps_the_clocks_own_timezone():
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)

    assert start_at_from(time(21, 0), now).tzinfo is timezone.utc


def test_a_start_time_exactly_ten_minutes_away_is_accepted():
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)  # 19:00 KST

    assert start_at_from(time(19, 10), now) == now + timedelta(minutes=10)


def test_a_start_time_inside_the_lead_time_is_rejected():
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)  # 19:00 KST

    with pytest.raises(ReservationStateError, match="10분 이후"):
        start_at_from(time(19, 9), now)


def test_a_start_time_already_past_in_seoul_is_rejected():
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)  # 19:00 KST

    with pytest.raises(ReservationStateError, match="10분 이후"):
        start_at_from(time(9, 0), now)


def test_an_untaken_reservation_is_editable():
    ensure_editable(ReservationStatus.OPEN, FUTURE, 0, NOW)


def test_a_reservation_with_a_participant_is_not_editable():
    with pytest.raises(ReservationStateError, match="참가자가 있는 예약"):
        ensure_editable(ReservationStatus.OPEN, FUTURE, 1, NOW)


def test_a_matched_reservation_is_not_editable():
    """Matched means the capacity is filled, so somebody is committed to it."""
    with pytest.raises(ReservationStateError, match="참가자가 있는 예약"):
        ensure_editable(ReservationStatus.MATCHED, FUTURE, 1, NOW)


def test_a_cancelled_reservation_is_not_editable():
    with pytest.raises(ReservationStateError, match="취소되었거나 종료된"):
        ensure_editable(ReservationStatus.CANCELLED, FUTURE, 0, NOW)


def test_a_reservation_that_already_started_is_not_editable():
    with pytest.raises(ReservationStateError, match="이미 시작된"):
        ensure_editable(ReservationStatus.OPEN, NOW, 0, NOW)
