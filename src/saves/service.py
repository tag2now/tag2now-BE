"""TTT2 saves: anyone's ranks for a profile, and an admin's reads and edits.

The profile read goes through a cache. The game rewrites the save when a
session ends, and a rank seen a few minutes late costs nothing, so an answer is
kept for cache_ttl_player_save --- a missing save too, or a profile with no save
would ask the server every time. An admin's written edit drops the entry at once.

The current-rank leaderboard and its holders come from one read of every save,
cached for cache_ttl_current_rank_leaderboard as the leaderboard's two best
characters per player and, per rank, who plays a character there --- so a
request decodes only the slice it needs. Each request filters and slices it.
Only what the game wrote counts: an admin's edit keeps the save's data_id,
which save-admin uses to skip unchanged saves, so it does not show there.

Admin calls go straight to the server, which checks the admin's password with
RPCN every time.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from itertools import groupby

from auth.models import AuthUser
from saves.ports import SaveServer
from saves.exceptions import SaveNotFoundError
from saves.models import HOLDER_RANKS, SaveLogRequest, SaveRequest
from shared.cache import cache_delete, cache_get, cache_set
from shared.settings import get_settings
from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS

logger = logging.getLogger(__name__)

# Audit fields that hold a path on the RPCN host; only the file's label means
# anything here, and the path says nothing an admin needs.
_PATH_FIELDS = ("backup", "source")


# --- profile --------------------------------------------------------------------

def _key(npid: str) -> str:
    # RPCN usernames are unique regardless of case, and an admin may type any case.
    return f"saves:player:{npid.casefold()}"


def _profile(save: dict | None) -> dict | None:
    if save is None:
        return None
    return {"username": save["npid"], "saved_at": _saved_at(save), "account_rank": save["account_rank"],
            "total": save["total"], "wins": save["wins"], "losses": save["losses"], "chars": save["chars"]}


# --- current rank: leaderboard and holders --------------------------------------

_CURRENT_RANK_KEY = "saves:current-rank-leaderboard"

# Stands in for a second character a player does not have; below any rank.
_NO_CHAR = {"rank": -1, "points": -1}


def _holders_key(rank: int) -> str:
    return f"saves:current-rank-holders:{rank}"


def _top_two(chars: list[dict]) -> list[dict]:
    # A stable sort keeps the lower id on a tie, as save-admin's own top two did.
    return sorted(chars, key=lambda c: (c["rank"], c["points"]), reverse=True)[:2]


def _holders_by_rank(players: list[dict], places: dict[str, int]) -> dict[int, list[dict]]:
    by_rank = {rank: [] for rank in HOLDER_RANKS}
    for player in players:
        for rank, ids in _played_ids_by_rank(player["chars"]).items():
            by_rank[rank].append({"npid": player["npid"], "saved_utc": player["saved_utc"],
                                  "account_rank": player["account_rank"],
                                  "place": places[player["npid"]], "chars": ids})
    return by_rank


def _played_ids_by_rank(chars: list[dict]) -> dict[int, list[int]]:
    played = {}
    for c in filter(_holds_its_rank, chars):
        played.setdefault(c["rank"], []).append(c["id"])
    return played


def _holds_its_rank(char: dict) -> bool:
    # The floor gives every character a rank; only one played there makes a holder.
    return bool(char["wins"] or char["losses"]) and char["rank"] in HOLDER_RANKS


def _holder(holder: dict) -> dict:
    return {"username": holder["npid"], "saved_at": _saved_at(holder), "account_rank": holder["account_rank"],
            "chars": [{"id": i, "character": TTT2_CHARACTERS[i]} for i in holder["chars"]]}


def _without_excluded(players: list[dict]) -> list[dict]:
    settings = get_settings()
    return [p for p in players if not settings.is_ranking_excluded(p["npid"])]


def _saved_within(players: list[dict], days: int | None) -> list[dict]:
    if days is None:
        return players
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return [p for p in players if _saved_at(p) >= since]


def current_rank_board(players: list[dict]) -> list[dict]:
    """Players with a ranked character, best first; equal standings share a place
    (1, 2, 2, 4) and are listed by name."""
    ranked = sorted((p for p in players if p["chars"]), key=lambda p: (_standing(p), p["npid"].casefold()))
    board, place = [], 1
    for _, tied in groupby(ranked, key=_standing):
        tied = list(tied)
        board += [{"rank": place, **_entry(p)} for p in tied]
        place += len(tied)
    return board


def _standing(player: dict) -> tuple:
    # Sorts ascending, so higher ranks and points come first.
    first, second = (player["chars"] + [_NO_CHAR, _NO_CHAR])[:2]
    return -first["rank"], -second["rank"], -first["points"], -second["points"]


def _entry(player: dict) -> dict:
    return {"username": player["npid"], "saved_at": _saved_at(player), "account_rank": player["account_rank"],
            "chars": player["chars"]}


# --- admin ----------------------------------------------------------------------

def _audit_record(record: dict) -> dict:
    head = ("ts", "user", "action", "npid")
    details = {k: _label(v) if k in _PATH_FIELDS else v for k, v in record.items() if k not in head}
    return {"ts": record["ts"], "user": record["user"], "action": record["action"],
            "username": record["npid"], "details": details}


def _label(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _saved_at(save: dict) -> datetime:
    # saved_utc is a naive UTC "YYYY-MM-DD HH:MM:SS[.ffffff]"
    return datetime.fromisoformat(save["saved_utc"]).replace(tzinfo=timezone.utc)


class SavesService:
    def __init__(self, server: SaveServer):
        self._server = server

    async def get_player_save(self, npid: str) -> dict:
        key = _key(npid)
        if (entry := cache_get(key)) is None:
            entry = {"save": _profile(await self._server.read(npid))}
            cache_set(key, entry, get_settings().cache_ttl_player_save)
        if entry["save"] is None:
            raise SaveNotFoundError("이 플레이어의 TTT2 세이브가 없습니다.")
        return entry["save"]

    async def get_current_rank_leaderboard(self, top: int, days: int | None = None) -> dict:
        # Filtering and ranking 1000 players per request costs about a millisecond,
        # so `days` needs no key of its own.
        if (players := cache_get(_CURRENT_RANK_KEY)) is None:
            players, _ = await self._fill_current_rank_cache()
        board = current_rank_board(_saved_within(_without_excluded(players), days))
        return {"total": len(board), "entries": board[:top]}

    async def get_current_rank_holders(self, rank: int, top: int, days: int) -> dict:
        """Recent players with a character they play at `rank`, the lowest on the
        leaderboard first: a strong player's other characters are lifted by rank
        correction, and this looks for players who belong at that rank."""
        if (holders := cache_get(_holders_key(rank))) is None:
            _, by_rank = await self._fill_current_rank_cache()
            holders = by_rank[rank]
        found = sorted(_saved_within(_without_excluded(holders), days),
                       key=lambda h: (-h["place"], h["npid"].casefold()))
        return {"rank": rank, "rank_name": TEKKEN_RANKS[rank]["name"], "total": len(found),
                "entries": [_holder(h) for h in found[:top]]}

    async def _fill_current_rank_cache(self) -> tuple[list[dict], dict[int, list[dict]]]:
        """Read every save once and cache both views of it, an empty rank included,
        so a rank no one plays is not asked of save-admin every time."""
        started = time.perf_counter()
        players = await self._server.read_ranks()
        board = [{**p, "chars": _top_two(p["chars"])} for p in players]
        places = {e["username"]: e["rank"] for e in current_rank_board(board)}
        by_rank = _holders_by_rank(players, places)
        ttl = get_settings().cache_ttl_current_rank_leaderboard
        cache_set(_CURRENT_RANK_KEY, board, ttl)
        for rank, holders in by_rank.items():
            cache_set(_holders_key(rank), holders, ttl)
        logger.info("current rank cache filled: %d players, %d holders, largest rank %d, %.0f ms",
                    len(players), sum(map(len, by_rank.values())), max(map(len, by_rank.values())),
                    (time.perf_counter() - started) * 1000)
        return board, by_rank

    async def show_save(self, admin: AuthUser, request: SaveRequest) -> dict:
        save = await self._admin_call("show", admin, request)
        return {**save, "username": save["npid"], "saved_at": _saved_at(save)}

    async def list_backups(self, admin: AuthUser, request: SaveRequest) -> dict:
        return await self._admin_call("backups", admin, request)

    async def read_save_log(self, admin: AuthUser, request: SaveLogRequest) -> dict:
        answer = await self._admin_call("log", admin, request)
        return {"records": [_audit_record(r) for r in answer["records"]]}

    async def edit_save(self, action: str, admin: AuthUser, request: SaveRequest) -> dict:
        """set-rank, set-account-rank, floor or restore: a preview with dry_run, else the write"""
        answer = await self._admin_call(action, admin, request)
        # Profiles show the save from a cache; a written one shows at once.
        if answer["applied"]:
            cache_delete(_key(answer["username"]))
        return answer

    async def _admin_call(self, action: str, admin: AuthUser, request) -> dict:
        payload = request.model_dump(exclude={"password"}, exclude_none=True)
        return await self._server.call(action, admin.username, request.password, payload)
