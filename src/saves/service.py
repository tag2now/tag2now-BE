"""A player's TTT2 save, read through a cache.

The game rewrites the save when a session ends, and a rank seen a few minutes
late costs nothing, so an answer is kept for cache_ttl_player_save --- a
missing save too, or a profile with no save would ask the server every time.
An admin's edit drops the entry at once (forget).
"""

from datetime import datetime, timezone

from saves.db import get_player_saves
from saves.exceptions import PlayerSaveNotFoundError
from shared.cache import cache_delete_pattern, cache_get, cache_set
from shared.settings import get_settings


def _key(npid: str) -> str:
    # RPCN usernames are unique regardless of case, and an admin may type any case.
    return f"saves:player:{npid.casefold()}"


async def get_player_save(npid: str) -> dict:
    key = _key(npid)
    if (entry := cache_get(key)) is None:
        entry = {"save": _profile(await get_player_saves().read(npid))}
        cache_set(key, entry, get_settings().cache_ttl_player_save)
    if entry["save"] is None:
        raise PlayerSaveNotFoundError("이 플레이어의 TTT2 세이브가 없습니다.")
    return entry["save"]


def forget(npid: str) -> None:
    cache_delete_pattern(_key(npid))


def _profile(save: dict | None) -> dict | None:
    if save is None:
        return None
    # saved_utc is a naive UTC "YYYY-MM-DD HH:MM:SS[.ffffff]"
    saved_at = datetime.fromisoformat(save["saved_utc"]).replace(tzinfo=timezone.utc)
    return {"username": save["npid"], "saved_at": saved_at, "account_rank": save["account_rank"],
            "total": save["total"], "wins": save["wins"], "losses": save["losses"], "chars": save["chars"]}
