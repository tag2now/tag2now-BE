"""Data models for match records."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import NamedTuple

from pydantic import BaseModel

from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS


class MatchOutcome(StrEnum):
    WIN = "win"
    LOSS = "loss"


class Side(IntEnum):
    """1P or 2P: RPCN's room slot, or 1P for the only player a roomless match has."""

    P1 = 1
    P2 = 2

    @property
    def other(self) -> "Side":
        return Side.P2 if self is Side.P1 else Side.P1


class EventStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    DEAD = "dead"


class CharTally(NamedTuple):
    wins: int
    losses: int
    # None in a state kept before saves carried ranks.
    rank: int | None = None


@dataclass(frozen=True)
class PlayerSave:
    """One save's cumulative tally."""

    npid: str
    data_id: int
    saved_at: datetime
    wins: int
    losses: int
    tallies: dict[int, CharTally]
    # Set on a start save only: who entered the match, in tag order.
    entered_chars: tuple[int, ...] = ()

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
            tallies={char["id"]: CharTally(char["wins"], char["losses"], char.get("rank")) for char in answer["chars"]},
            entered_chars=tuple(answer["own_chars"]),
        )


@dataclass(frozen=True)
class PlayerMatch:
    """One player's part in a finished match, as their saves showed it."""

    outcome: MatchOutcome
    chars: tuple[int, ...]
    # Each character's rank going into the match, in the order of `chars`.
    ranks: tuple[int | None, ...]


@dataclass(frozen=True)
class Comparison:
    """What changed between two saves: a match, or a jump that cannot be split into matches."""

    match: PlayerMatch | None = None
    merged: bool = False


@dataclass(frozen=True)
class MatchEvent:
    id: int
    npid: str
    outcome: MatchOutcome
    chars: tuple[int, ...]
    saved_at: datetime
    # None on an event queued before ranks were kept.
    ranks: tuple[int | None, ...] | None = None
    attempts: int = 0


@dataclass(frozen=True)
class MatchPlayer:
    """One player in a recorded match. `chars` and `ranks` are None when their save was not seen."""

    npid: str
    online_name: str | None
    outcome: MatchOutcome
    chars: tuple[int, ...] | None
    ranks: tuple[int | None, ...] | None


@dataclass(frozen=True)
class RecordedMatch:
    """A match as the records list shows it, by side. `p2` is None when no room named the opponent."""

    id: int
    played_at: datetime
    p1: MatchPlayer
    p2: MatchPlayer | None


@dataclass(frozen=True)
class WeeklyPlayer:
    """A player ranked by the matches their own save showed."""

    npid: str
    online_name: str
    match_count: int
    wins: int
    losses: int


@dataclass(frozen=True)
class OpponentRecord:
    """One opponent of a player, with that player's wins and losses against them."""

    npid: str
    online_name: str
    match_count: int
    wins: int
    losses: int


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


class RecordPlayerOut(BaseModel):
    npid: str
    # From the room the match was played in.
    online_name: str | None
    # The JSON key the frontend reads; `outcome` everywhere else.
    result: MatchOutcome
    # Null when this player's save was not seen.
    chars: list[RecordCharOut] | None

    @classmethod
    def of(cls, player: MatchPlayer) -> "RecordPlayerOut":
        return cls(npid=player.npid, online_name=player.online_name, result=player.outcome, chars=_chars_out(player))


def _chars_out(player: MatchPlayer) -> list[RecordCharOut] | None:
    if player.chars is None:
        return None
    ranks = player.ranks or (None,) * len(player.chars)
    return [RecordCharOut.of(char_id, rank) for char_id, rank in zip(player.chars, ranks)]


class MatchRecordOut(BaseModel):
    id: int
    played_at: datetime
    p1: RecordPlayerOut
    # Null when no room named the opponent.
    p2: RecordPlayerOut | None

    @classmethod
    def of(cls, match: RecordedMatch) -> "MatchRecordOut":
        return cls(
            id=match.id,
            played_at=match.played_at,
            p1=RecordPlayerOut.of(match.p1),
            p2=None if match.p2 is None else RecordPlayerOut.of(match.p2),
        )


class MatchRecordPageOut(BaseModel):
    matches: list[MatchRecordOut]
    # Pass as `before` for the next page; null on the last.
    next_before: int | None
