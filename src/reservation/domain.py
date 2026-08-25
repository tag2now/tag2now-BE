"""Framework-independent reservation domain types and rules."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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


LIVE_STATUSES = (ReservationStatus.OPEN, ReservationStatus.MATCHED)


def ensure_conditions_valid(match_type: MatchType, ranks: list[str], capacity: int) -> None:
    """Rank matches are one-on-one and rank-scoped; player matches are neither."""
    if match_type is MatchType.RANK:
        if not ranks:
            raise ReservationStateError("Rank matches require at least one rank")
        if capacity != 1:
            raise ReservationStateError("Rank matches have a capacity of one")
    elif ranks:
        raise ReservationStateError("Player matches do not use ranks")


def status_for(participant_count: int, capacity: int) -> ReservationStatus:
    """A live reservation is matched once its participants fill the capacity."""
    return ReservationStatus.MATCHED if participant_count >= capacity else ReservationStatus.OPEN


def ensure_joinable(status: ReservationStatus, start_at: datetime, participant_count: int, capacity: int, now: datetime) -> None:
    if status is not ReservationStatus.OPEN or start_at <= now:
        raise ReservationStateError("Reservation is not open for joining")
    if participant_count >= capacity:
        raise ReservationStateError("Reservation is full")


def ensure_participation_cancellable(status: ReservationStatus, start_at: datetime, now: datetime) -> None:
    if status not in LIVE_STATUSES:
        raise ReservationStateError("Reservation is no longer active")
    if start_at <= now:
        raise ReservationStateError("Reservation has started")
