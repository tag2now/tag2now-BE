"""Activity application service — cached queries."""

from activity.db import get_activity_repo
from shared.cache import cache_get, cache_set
from shared.settings import get_settings


async def record_activity(player_npids: list[str], total_players: int) -> None:
    """Record a snapshot (delegates to repository)."""
    await get_activity_repo().record_activity(player_npids, total_players)


async def get_global_activity(com_id: str) -> list[dict]:
    """Return hourly activity averages, cached."""
    key = f"ttt2:stats_activity:{com_id}"
    if cached := cache_get(key):
        return cached
    result = await get_activity_repo().get_global_activity()
    cache_set(key, result, get_settings().cache_ttl_rooms)
    return result


async def get_player_hours(npid: str) -> list[int]:
    """Return hours when player is typically online."""
    return await get_activity_repo().get_player_hours(npid)
