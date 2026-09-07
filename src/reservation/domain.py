"""Framework-independent reservation domain types and rules."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from reservation.exceptions import ReservationStateError


class MatchType(StrEnum):
    RANK = "rank_match"
    PLAYER = "player_match"
    ANY = "any"


class ReservationStatus(StrEnum):
    OPEN = "open"
    MATCHED = "matched"
    CANCELLED = "cancelled"
    ENDED = "ended"


@dataclass(frozen=True)
class Reservation:
    id: int
    start_at: datetime
    host_display_name: str
    host_ranks: list[str]
    match_type: MatchType
    capacity: int
    memo: str
    status: ReservationStatus
    participant_count: int
    created_at: datetime


@dataclass(frozen=True)
class Participant:
    id: int
    reservation_id: int
    display_name: str
    ranks: list[str]
    joined_at: datetime


KST = ZoneInfo("Asia/Seoul")
LIVE_STATUSES = (ReservationStatus.OPEN, ReservationStatus.MATCHED)
LEAD_TIME = timedelta(minutes=10)

# A play session ends at dawn, not at midnight, so the day boundary is 06:00 KST.
DAY_END_HOUR = 6

# How long a reservation stays alive once it has started.
#
# Hosts used to declare how long they expected to play, and that estimate drove
# expiry. Nobody can predict it — a set runs long or ends in ten minutes — so a
# reservation now simply outlives its start by a fixed hour. That hour is also
# the only window in which the detail page is reachable, since the listing is
# how anyone gets to it.
LISTING_GRACE = timedelta(hours=1)


def window_end(now: datetime) -> datetime:
    """The next 06:00 KST — today's if dawn has not come yet, tomorrow's otherwise.

    This is the far edge of everything the reservation tab shows and accepts:
    at 02:00 it is four hours away, at 21:00 it is nine.
    """
    kst_now = now.astimezone(KST)
    end = kst_now.replace(hour=DAY_END_HOUR, minute=0, second=0, microsecond=0)
    if kst_now >= end:
        end += timedelta(days=1)
    return end.astimezone(now.tzinfo)


def start_at_from(start_time: time, now: datetime) -> datetime:
    """Resolve a wall-clock KST time to the next instant it denotes.

    Hosts pick a time of day, not a date. 21:00 means 21:00 KST today, but a
    time of day that Seoul has already passed rolls over to tomorrow — at 23:00
    a host picking 00:30 means half an hour from now, not twenty-three and a
    half hours ago. The result is returned in the clock's own zone so that
    callers compare like with like.
    """
    start_at = datetime.combine(now.astimezone(KST).date(), start_time, tzinfo=KST).astimezone(now.tzinfo)
    if start_at < now:
        start_at += timedelta(days=1)
    if start_at < now + LEAD_TIME:
        raise ReservationStateError("지금부터 10분 이후 시각으로 예약할 수 있습니다.")
    if start_at >= window_end(now):
        # Anything past dawn would be created into a window nobody can see.
        raise ReservationStateError("지금부터 다음 날 오전 6시 사이의 시각만 예약할 수 있습니다.")
    return start_at


def ensure_conditions_valid(match_type: MatchType, ranks: list[str], capacity: int) -> None:
    """Rank matches are one-on-one and rank-scoped; player matches are neither.

    ANY takes either game, so it borrows neither rule: ranks and capacity are free.
    """
    if match_type is MatchType.RANK:
        if not ranks:
            raise ReservationStateError("랭크매치는 보유 계급을 하나 이상 선택해야 합니다.")
        if capacity != 1:
            raise ReservationStateError("랭크매치는 1명만 모집할 수 있습니다.")
    elif match_type is MatchType.PLAYER and ranks:
        raise ReservationStateError("플레이어 매치는 계급을 선택하지 않습니다.")


def ends_at(start_at: datetime) -> datetime:
    """The instant a reservation stops being live, an hour after it starts."""
    return start_at + LISTING_GRACE


def status_for(participant_count: int, capacity: int) -> ReservationStatus:
    """A live reservation is matched once its participants fill the capacity."""
    return ReservationStatus.MATCHED if participant_count >= capacity else ReservationStatus.OPEN


def ensure_joinable(status: ReservationStatus, start_at: datetime, participant_count: int, capacity: int, now: datetime) -> None:
    if status is not ReservationStatus.OPEN or start_at <= now:
        raise ReservationStateError("지금은 참가할 수 없는 예약입니다.")
    if participant_count >= capacity:
        raise ReservationStateError("모집이 마감된 예약입니다.")


def ensure_editable(status: ReservationStatus, start_at: datetime, participant_count: int, now: datetime) -> None:
    """A reservation may be edited only while nobody is committed to it.

    Participants agreed to the conditions as they stood when they joined; the
    host changing the time or the match type underneath them would bind people
    to an appointment they never accepted. Editing therefore stops at the first
    participant, and the host cancels and re-posts instead.
    """
    if status not in LIVE_STATUSES:
        raise ReservationStateError("이미 취소되었거나 종료된 예약입니다.")
    if start_at <= now:
        raise ReservationStateError("이미 시작된 예약은 변경할 수 없습니다.")
    if participant_count > 0:
        raise ReservationStateError("참가자가 있는 예약은 수정할 수 없습니다. 삭제 후 다시 등록해 주세요.")


def ensure_participation_cancellable(status: ReservationStatus, start_at: datetime, now: datetime) -> None:
    if status not in LIVE_STATUSES:
        raise ReservationStateError("이미 취소되었거나 종료된 예약입니다.")
    if start_at <= now:
        raise ReservationStateError("이미 시작된 예약은 변경할 수 없습니다.")
