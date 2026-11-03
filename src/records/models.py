"""Data models for match records."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel

from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS


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
    # None in a state kept before saves carried ranks.
    rank: int | None = None


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
            # .get: a save-admin older than ranks answers none.
            chars={char["id"]: CharRecord(char["wins"], char["losses"], char.get("rank")) for char in answer["chars"]},
            own_chars=tuple(answer["own_chars"]),
        )


@dataclass(frozen=True)
class FinishedMatch:
    result: MatchOutcome
    chars: tuple[int, ...]
    # Each character's rank going into the match, in the order of `chars`.
    ranks: tuple[int | None, ...]


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
    # None on an event queued before ranks were kept.
    ranks: tuple[int | None, ...] | None = None
    attempts: int = 0


@dataclass(frozen=True)
class MatchSide:
    """One player in a recorded match. `chars` and `ranks` are None when their save was not seen."""

    npid: str
    online_name: str | None
    chars: tuple[int, ...] | None
    ranks: tuple[int | None, ...] | None


@dataclass(frozen=True)
class RecordedMatch:
    """A match as the records list shows it. A side is None when no room named the opponent."""

    id: int
    played_at: datetime
    winner: MatchSide | None
    loser: MatchSide | None


# -- Responses -----------------------------------------------------------------


class RankOut(BaseModel):
    name: str
    tier: str


class RecordCharOut(BaseModel):
    name: str
    # The rank the character went into the match at; null on matches recorded before ranks were kept.
    rank: RankOut | None

    @classmethod
    def of(cls, char_id: int, rank: int | None) -> "RecordCharOut":
        known = TEKKEN_RANKS.get(rank)
        return cls(
            name=TTT2_CHARACTERS.get(char_id, str(char_id)),
            rank=None if known is None else RankOut(**known),
        )


class RecordSideOut(BaseModel):
    npid: str
    # From the room the match was played in.
    online_name: str | None
    # Null when this side's save was not seen.
    chars: list[RecordCharOut] | None

    @classmethod
    def of(cls, side: MatchSide) -> "RecordSideOut":
        return cls(npid=side.npid, online_name=side.online_name, chars=_chars_out(side))


def _chars_out(side: MatchSide) -> list[RecordCharOut] | None:
    if side.chars is None:
        return None
    ranks = side.ranks or (None,) * len(side.chars)
    return [RecordCharOut.of(char_id, rank) for char_id, rank in zip(side.chars, ranks)]


class MatchRecordOut(BaseModel):
    id: int
    played_at: datetime
    # Null when no room named the opponent.
    winner: RecordSideOut | None
    loser: RecordSideOut | None

    @classmethod
    def of(cls, match: RecordedMatch) -> "MatchRecordOut":
        return cls(
            id=match.id,
            played_at=match.played_at,
            winner=_side_out(match.winner),
            loser=_side_out(match.loser),
        )


def _side_out(side: MatchSide | None) -> RecordSideOut | None:
    return None if side is None else RecordSideOut.of(side)


class MatchRecordPageOut(BaseModel):
    matches: list[MatchRecordOut]
    # Pass as `before` for the next page; null on the last.
    next_before: int | None
