"""Data models for match records."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import NamedTuple


class MatchOutcome(StrEnum):
    WIN = "win"
    LOSS = "loss"

    @property
    def opposite(self) -> "MatchOutcome":
        return MatchOutcome.LOSS if self is MatchOutcome.WIN else MatchOutcome.WIN


class EventStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    DEAD = "dead"


class CharRecord(NamedTuple):
    wins: int
    losses: int


@dataclass(frozen=True)
class PlayerSave:
    """One save's cumulative record."""

    npid: str
    data_id: int
    saved_at: datetime
    wins: int
    losses: int
    chars: dict[int, CharRecord]
    # Set on a start save only: who entered the match, in tag order.
    own_chars: tuple[int, ...] = ()

    @classmethod
    def from_answer(cls, answer: dict) -> "PlayerSave":
        """save-admin's text is RPCN's clock in UTC, with no offset."""
        return cls(
            npid=answer["npid"],
            data_id=answer["data_id"],
            saved_at=datetime.fromisoformat(answer["saved_utc"]).replace(tzinfo=timezone.utc),
            wins=answer["wins"],
            losses=answer["losses"],
            chars={c["id"]: CharRecord(c["wins"], c["losses"]) for c in answer["chars"]},
            own_chars=tuple(answer["own_chars"]),
        )


@dataclass(frozen=True)
class FinishedMatch:
    result: MatchOutcome
    chars: tuple[int, ...]


@dataclass(frozen=True)
class Comparison:
    """What changed between two saves: a match, or a jump that cannot be split into matches."""

    match: FinishedMatch | None = None
    merged: bool = False


@dataclass(frozen=True)
class MatchEvent:
    id: int
    npid: str
    result: MatchOutcome
    chars: tuple[int, ...]
    saved_at: datetime
    attempts: int = 0
