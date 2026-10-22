"""TTT2 application service — orchestrates ports, caching, and domain logic."""

import asyncio
import logging

from fastapi.encoders import jsonable_encoder

from shared.cache import cache_get, cache_set
from shared.settings import get_settings
from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS
from matching.db import get_game_server_repo
from matching.matchmaking_tracker import update_and_get_phantoms
from matching.models import (
    RoomInfoDTO,
    ActivityObservation,
    RoomType,
)
from streaming import service as streaming_service

logger = logging.getLogger(__name__)

# The leaderboard is fetched once at this size and cached; every request slices from it.
LEADERBOARD_CACHE_SIZE = 500


# ---------------------------------------------------------------------------
# Pure domain functions
# ---------------------------------------------------------------------------

def _group_rooms_by_type(rooms: list[RoomInfoDTO]) -> dict[str, list[RoomInfoDTO]]:
    grouped: dict[str, list[RoomInfoDTO]] = {RoomType.PLAYER_MATCH.value: [], RoomType.RANK_MATCH.value: []}
    for room in rooms:
        grouped[room.room_type.value].append(room)
    return grouped


def get_game_data() -> dict:
    """Character and rank tables; tag2now-save-admin reads them from here."""
    return {
        "characters": [{"id": i, "name": name} for i, name in sorted(TTT2_CHARACTERS.items())],
        "ranks": [{"id": i, **rank} for i, rank in sorted(TEKKEN_RANKS.items())],
    }


# ---------------------------------------------------------------------------
# Cached application services
# ---------------------------------------------------------------------------

def get_server_world_tree(com_id: str) -> dict[str, list[int]]:
    """Return {server_id_str: [world_ids]}, cached."""
    key = f"ttt2:servers:{com_id}"
    if cached := cache_get(key):
        return cached
    repo = get_game_server_repo()
    tree = repo.get_server_world_tree(com_id)
    serializable = {str(k): v for k, v in tree.items()}
    cache_set(key, serializable, get_settings().cache_ttl_servers)
    return serializable


def _get_all_worlds(com_id: str) -> list[int]:
    tree = get_server_world_tree(com_id)
    return [w for worlds in tree.values() for w in worlds]


def _fetch_rooms_all(com_id: str):
    """Blocking: fetch all rooms and apply matchmaking detection."""
    repo = get_game_server_repo()
    rooms = repo.search_rooms_all(com_id, _get_all_worlds(com_id))
    grouped = _group_rooms_by_type(rooms)

    all_room_dtos = grouped[RoomType.PLAYER_MATCH.value] + grouped[RoomType.RANK_MATCH.value]
    phantom_rooms = update_and_get_phantoms(all_room_dtos)
    grouped[RoomType.RANK_MATCH.value].extend(phantom_rooms)
    grouped[RoomType.RANK_MATCH.value].sort(key=lambda r: r.rank_info.id if r.rank_info else -1)
    return grouped


def _fetch_activity_observation(com_id: str) -> ActivityObservation:
    """Blocking RPCN read used by the independent history collector.

    This deliberately bypasses the HTTP response cache: collection must not
    depend on a visitor requesting the rooms endpoint.
    """
    repo = get_game_server_repo()
    rooms = repo.search_rooms_all(com_id, _get_all_worlds(com_id))
    rank_rooms = [room for room in rooms if room.room_type == RoomType.RANK_MATCH and room.current_members >= 1]
    return ActivityObservation(
        rank_player_npids={
        user.npid
        for room in rank_rooms
        for user in room.users
        if user.npid
        },
        total_players=sum(len(room.users) for room in rooms), total_rooms=len(rooms),
        rank_players=sum(len(room.users) for room in rank_rooms), rank_rooms=len(rank_rooms),
        rank_matches=[room for room in rank_rooms if room.current_members == 2],
    )


async def collect_activity_observation(com_id: str) -> ActivityObservation:
    """Fetch current player counts and rank participants without caching."""
    return await asyncio.to_thread(_fetch_activity_observation, com_id)


async def get_rooms_all(com_id: str) -> dict:
    """Search all rooms including hidden, with matchmaking detection and who is live. Cached."""
    key = f"ttt2:rooms_all:{com_id}"
    if cached := cache_get(key):
        return cached

    result = await asyncio.to_thread(_fetch_rooms_all, com_id)
    encoded = jsonable_encoder(result)
    await _attach_streams(encoded)
    cache_set(key, encoded, get_settings().cache_ttl_rooms_all)
    return encoded


async def _attach_streams(groups: dict) -> None:
    """Set each room user's `stream` to their live broadcast, or None."""
    users = [user for rooms in groups.values() for room in rooms for user in room["users"]]
    try:
        live = await streaming_service.live_for({user["npid"] for user in users if user.get("npid")})
    except Exception:
        # Streams are an extra: the room list still goes out without them.
        logger.warning("Live streams unavailable; rooms served without them", exc_info=True)
        live = {}
    for user in users:
        user["stream"] = live.get((user.get("npid") or "").lower())


def get_leaderboard(com_id: str, board_id: int, num_ranks: int) -> dict:
    """Return the top N entries, sliced from the single cached full leaderboard."""
    full = _get_full_leaderboard(com_id, board_id)
    return {**full, "entries": full["entries"][:num_ranks]}


def _leaderboard_cache_key(com_id: str, board_id: int) -> str:
    return f"ttt2:leaderboard:{com_id}:{board_id}"


def _get_full_leaderboard(com_id: str, board_id: int) -> dict:
    """Fetch the full leaderboard, cached under one key regardless of requested size."""
    key = _leaderboard_cache_key(com_id, board_id)
    if cached := cache_get(key):
        return cached
    repo = get_game_server_repo()
    lb = repo.get_leaderboard(com_id, board_id, LEADERBOARD_CACHE_SIZE)
    encoded = _without_excluded(jsonable_encoder(lb))
    cache_set(key, encoded, get_settings().cache_ttl_leaderboard)
    return encoded


def _without_excluded(lb: dict) -> dict:
    """Drop excluded accounts; those below move up past them, and ties stay tied."""
    settings = get_settings()
    excluded_ranks = [e["rank"] for e in lb["entries"] if settings.is_ranking_excluded(e["np_id"])]
    entries = [
        {**e, "rank": e["rank"] - sum(r < e["rank"] for r in excluded_ranks)}
        for e in lb["entries"] if not settings.is_ranking_excluded(e["np_id"])
    ]
    return {**lb, "total_records": lb["total_records"] - len(excluded_ranks), "entries": entries}
