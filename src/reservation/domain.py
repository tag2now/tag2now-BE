"""Framework-independent reservation domain types."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
