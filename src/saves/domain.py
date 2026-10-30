"""Who stands where at their current rank, and who plays at a rank now.

The shapes are TypedDicts, not classes: they are what save-admin answers and
what the cache holds as JSON, and every request reads them back, so they stay
plain dicts at no cost of conversion.
"""

from datetime import datetime, timedelta, timezone
from itertools import groupby
from typing import TypedDict, TypeVar

# The floor has raised every save to 1st dan (10), so no one plays below it.
HOLDER_RANKS = range(10, 43)


class RankedChar(TypedDict):
    id: int
    character: str
    rank: int
    rank_name: str
    tier: str
    points: int
    streak: int
    wins: int
    losses: int


class PlayerRanks(TypedDict):
    npid: str
    # A naive UTC "YYYY-MM-DD HH:MM:SS[.ffffff]".
    saved_utc: str
    account_rank: int
    chars: list[RankedChar]


class Holder(TypedDict):
    npid: str
    saved_utc: str
    account_rank: int
    # The player's place on the current-rank leaderboard.
    place: int
    # Ids of the characters played at the rank this holder is listed under.
    chars: list[int]


class BoardEntry(TypedDict):
    rank: int
    username: str
    saved_at: datetime
    account_rank: int
    chars: list[RankedChar]


_Saved = TypeVar("_Saved", PlayerRanks, Holder)

# Stands in for a second character a player does not have; below any rank.
_NO_CHAR = {"rank": -1, "points": -1}


def saved_at(save: dict) -> datetime:
    """When the game last wrote the save, from any save-admin answer carrying `saved_utc`."""
    return datetime.fromisoformat(save["saved_utc"]).replace(tzinfo=timezone.utc)


def saved_within(players: list[_Saved], days: int | None, now: datetime) -> list[_Saved]:
    if days is None:
        return players
    since = now - timedelta(days=days)
    return [p for p in players if saved_at(p) >= since]


def top_two(chars: list[RankedChar]) -> list[RankedChar]:
    # A stable sort keeps the lower id on a tie, as save-admin's own top two did.
    return sorted(chars, key=lambda c: (c["rank"], c["points"]), reverse=True)[:2]


def holds_its_rank(char: RankedChar) -> bool:
    # The floor gives every character a rank; only one played there makes a holder.
    return bool(char["wins"] or char["losses"]) and char["rank"] in HOLDER_RANKS


def played_ids_by_rank(chars: list[RankedChar]) -> dict[int, list[int]]:
    played = {}
    for c in filter(holds_its_rank, chars):
        played.setdefault(c["rank"], []).append(c["id"])
    return played


def holders_by_rank(players: list[PlayerRanks], places: dict[str, int]) -> dict[int, list[Holder]]:
    """Every rank a player plays a character at lists them, an empty rank included."""
    by_rank = {rank: [] for rank in HOLDER_RANKS}
    for player in players:
        for rank, ids in played_ids_by_rank(player["chars"]).items():
            by_rank[rank].append(
                {
                    "npid": player["npid"],
                    "saved_utc": player["saved_utc"],
                    "account_rank": player["account_rank"],
                    "place": places[player["npid"]],
                    "chars": ids,
                }
            )
    return by_rank


def current_rank_board(players: list[PlayerRanks]) -> list[BoardEntry]:
    """Players with a ranked character, best first; equal standings share a place
    (1, 2, 2, 4) and are listed by name."""
    ranked = sorted((p for p in players if p["chars"]), key=lambda p: (_standing(p), p["npid"].casefold()))
    board, place = [], 1
    for _, tied in groupby(ranked, key=_standing):
        tied = list(tied)
        board += [{"rank": place, **_entry(p)} for p in tied]
        place += len(tied)
    return board


def _standing(player: PlayerRanks) -> tuple:
    # Sorts ascending, so higher ranks and points come first.
    first, second = (player["chars"] + [_NO_CHAR, _NO_CHAR])[:2]
    return -first["rank"], -second["rank"], -first["points"], -second["points"]


def _entry(player: PlayerRanks) -> dict:
    return {
        "username": player["npid"],
        "saved_at": saved_at(player),
        "account_rank": player["account_rank"],
        "chars": player["chars"],
    }
