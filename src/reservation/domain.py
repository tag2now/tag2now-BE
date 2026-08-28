"""Framework-independent reservation domain types and rules."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from reservation.exceptions import ReservationStateError


class MatchType(StrEnum):
    RANK = "rank_match"
    PLAYER = "player_match"


class ReservationStatus(StrEnum):
    OPEN = "open"
    MATCHED = "matched"
    CANCELLED = "cancelled"
    ENDED = "ended"


@dataclass(frozen=True)
class Reservation:
    id: int
    start_at: datetime
    duration_minutes: int
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


def start_at_from(start_time: time, now: datetime) -> datetime:
    """Resolve a wall-clock KST time to the instant it denotes today.

    Hosts pick a time of day, not a date: 21:00 means 21:00 KST on whatever day
    it currently is in Seoul. The result is returned in the clock's own zone so
    that callers compare like with like.
    """
    start_at = datetime.combine(now.astimezone(KST).date(), start_time, tzinfo=KST).astimezone(now.tzinfo)
    if start_at < now + LEAD_TIME:
        raise ReservationStateError("지금부터 10분 이후 시각으로 예약할 수 있습니다.")
    return start_at


def ensure_conditions_valid(match_type: MatchType, ranks: list[str], capacity: int) -> None:
    """Rank matches are one-on-one and rank-scoped; player matches are neither."""
    if match_type is MatchType.RANK:
        if not ranks:
            raise ReservationStateError("랭크매치는 보유 계급을 하나 이상 선택해야 합니다.")
        if capacity != 1:
            raise ReservationStateError("랭크매치는 1명만 모집할 수 있습니다.")
    elif ranks:
        raise ReservationStateError("플레이어 매치는 계급을 선택하지 않습니다.")


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
