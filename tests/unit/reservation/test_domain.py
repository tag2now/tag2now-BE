"""Reservation state rules are pure — they need no database."""

from datetime import datetime, time, timedelta, timezone

import pytest

from reservation.domain import (
    MatchType,
    ReservationStatus,
    ensure_cancellable,
    ensure_comment_deletable_by,
    ensure_commentable,
    ensure_conditions_valid,
    ensure_editable,
    ensure_edited_by_host,
    ensure_joinable,
    ensure_joinable_by,
    ensure_participation_cancellable,
    start_at_from,
    status_for,
    window_end,
)
from reservation.exceptions import ReservationAccessError, ReservationStateError

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
    with pytest.raises(ReservationStateError, match="모집이 완료된"):
        ensure_joinable(ReservationStatus.OPEN, FUTURE, 1, 1, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.OPEN, ReservationStatus.MATCHED])
def test_participation_in_a_live_future_reservation_is_cancellable(status):
    ensure_participation_cancellable(status, FUTURE, NOW, participating=True)


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.ENDED])
def test_participation_in_a_dead_reservation_is_not_cancellable(status):
    with pytest.raises(ReservationStateError, match="취소되었거나 종료된"):
        ensure_participation_cancellable(status, FUTURE, NOW, participating=True)


def test_participation_in_a_started_reservation_is_not_cancellable():
    with pytest.raises(ReservationStateError, match="이미 시작된"):
        ensure_participation_cancellable(ReservationStatus.OPEN, PAST, NOW, participating=True)


def test_only_a_participant_can_cancel_their_participation():
    with pytest.raises(ReservationAccessError, match="참가 중인 예약이 아닙니다"):
        ensure_participation_cancellable(ReservationStatus.OPEN, FUTURE, NOW, participating=False)


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


@pytest.mark.parametrize("capacity", [1, 2, 3])
def test_an_any_match_accepts_ranks_at_any_capacity(capacity):
    ensure_conditions_valid(MatchType.ANY, ["Brawler"], capacity)


@pytest.mark.parametrize("capacity", [1, 2, 3])
def test_an_any_match_accepts_no_ranks_at_any_capacity(capacity):
    ensure_conditions_valid(MatchType.ANY, [], capacity)


def test_a_start_time_resolves_against_todays_date_in_seoul():
    # 10:00 UTC is 19:00 KST on the same day
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)

    start_at = start_at_from(time(21, 0), now)

    assert start_at == datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)  # 21:00 KST


def test_seoul_today_is_already_tomorrow_late_in_the_utc_day():
    # 16:00 UTC is 01:00 KST the next day, so "today" in Seoul is the 25th
    now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)

    start_at = start_at_from(time(3, 0), now)

    assert start_at == datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)  # 25th 03:00 KST


def test_the_small_hours_cannot_book_the_coming_evening():
    """01:00 sits in the tail of the previous night: its window ends at 06:00.

    Tonight's 21:00 becomes bookable once dawn moves the window forward, which
    is the price of a window anchored to the session rather than to the date.
    """
    now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)  # 25th 01:00 KST

    with pytest.raises(ReservationStateError, match="오전 6시"):
        start_at_from(time(21, 0), now)


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


def test_a_start_time_already_past_in_seoul_rolls_over_to_tomorrow():
    """23:00 picking 00:30 means half an hour from now, not yesterday morning."""
    now = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)  # 23:00 KST

    start_at = start_at_from(time(0, 30), now)

    assert start_at == datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)  # 25th 00:30 KST


def test_a_rolled_over_time_past_dawn_is_rejected():
    """09:00 picked at 19:00 would land in a window nobody can see."""
    now = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)  # 19:00 KST

    with pytest.raises(ReservationStateError, match="오전 6시"):
        start_at_from(time(9, 0), now)


def test_a_start_time_at_or_after_the_window_end_is_rejected():
    now = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)  # 25th 05:00 KST

    with pytest.raises(ReservationStateError, match="오전 6시"):
        start_at_from(time(6, 0), now)


def test_a_start_time_just_inside_the_window_end_is_accepted():
    now = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)  # 25th 05:00 KST

    assert start_at_from(time(5, 59), now) == datetime(2026, 8, 24, 20, 59, tzinfo=timezone.utc)


def test_before_dawn_the_window_ends_at_this_mornings_six():
    now = datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc)  # 25th 02:00 KST

    assert window_end(now) == datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)  # 25th 06:00 KST


def test_after_dawn_the_window_ends_at_tomorrows_six():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)  # 21:00 KST

    assert window_end(now) == datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)  # 25th 06:00 KST


def test_the_window_end_keeps_the_clocks_own_timezone():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    assert window_end(now).tzinfo is timezone.utc


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


@pytest.mark.parametrize(
    "status",
    [ReservationStatus.OPEN, ReservationStatus.MATCHED, ReservationStatus.ENDED],
)
def test_a_reservation_can_be_commented_on_even_after_it_ends(status):
    """The page is shareable and the match happened; there is still something to say."""
    ensure_commentable(status)


def test_a_cancelled_reservation_takes_no_comments():
    with pytest.raises(ReservationStateError):
        ensure_commentable(ReservationStatus.CANCELLED)


def test_anyone_but_the_host_may_join():
    ensure_joinable_by("host", "joiner", already_joined=False)


def test_the_host_cannot_join_their_own_reservation():
    with pytest.raises(ReservationStateError, match="내가 만든 예약에는"):
        ensure_joinable_by("host", "host", already_joined=False)


def test_an_account_cannot_join_twice():
    with pytest.raises(ReservationStateError, match="이미 참가한"):
        ensure_joinable_by("host", "joiner", already_joined=True)


def test_anyone_may_join_a_reservation_from_before_login():
    ensure_joinable_by(None, "joiner", already_joined=False)


def test_the_host_edits_their_reservation():
    ensure_edited_by_host("host", "host")


@pytest.mark.parametrize("host_subject", ["host", None])
def test_nobody_else_edits_it_and_a_hostless_row_has_no_editor(host_subject):
    with pytest.raises(ReservationAccessError, match="예약한 사람만 수정"):
        ensure_edited_by_host(host_subject, "stranger")


@pytest.mark.parametrize("status", [ReservationStatus.OPEN, ReservationStatus.MATCHED])
def test_the_host_cancels_a_live_reservation_before_it_starts(status):
    ensure_cancellable("host", "host", status, FUTURE, NOW)


@pytest.mark.parametrize("host_subject", ["host", None])
def test_nobody_else_cancels_it_and_a_hostless_row_has_no_canceller(host_subject):
    with pytest.raises(ReservationAccessError, match="예약한 사람만 취소"):
        ensure_cancellable(host_subject, "stranger", ReservationStatus.OPEN, FUTURE, NOW)


@pytest.mark.parametrize("status", [ReservationStatus.CANCELLED, ReservationStatus.ENDED])
def test_a_dead_reservation_cannot_be_cancelled(status):
    with pytest.raises(ReservationAccessError, match="시작했거나 끝난"):
        ensure_cancellable("host", "host", status, FUTURE, NOW)


def test_a_started_reservation_cannot_be_cancelled():
    with pytest.raises(ReservationAccessError, match="시작했거나 끝난"):
        ensure_cancellable("host", "host", ReservationStatus.OPEN, NOW, NOW)


def test_the_author_deletes_their_comment():
    ensure_comment_deletable_by("author", "author")


@pytest.mark.parametrize("author_subject", ["author", None])
def test_nobody_else_deletes_it_and_an_authorless_comment_has_no_deleter(author_subject):
    with pytest.raises(ReservationAccessError, match="작성한 사람만 삭제"):
        ensure_comment_deletable_by(author_subject, "stranger")
