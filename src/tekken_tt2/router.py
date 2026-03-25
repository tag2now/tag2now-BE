"""FastAPI router for Tekken Tag Tournament 2 endpoints."""

import asyncio
import logging

from fastapi import APIRouter, Path, Query
from fastapi.encoders import jsonable_encoder
from shared.cache import cache_get, cache_set
from tekken_tt2.rpcn_lifecycle import api_client
from tekken_tt2.models import TTT2_COM_ID, TTT2_RANK_BOARD_ID
from tekken_tt2.matchmaking_tracker import update_and_get_matchmaking
from tekken_tt2.service import get_server_world_tree, get_rooms, get_rooms_all, get_leaderboard
from tekken_tt2 import activity_tracker
from tekken_tt2.service import lookup_player
from shared.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tekken Tag Tournament 2"])


def _get_all_worlds() -> list[int]:
    return [w for worlds in _get_world_tree().values() for w in worlds]


def _get_world_tree() -> dict[int, list[int]]:
    """Return {server_id: [world_ids]}, using the servers cache when available."""
    key = f"ttt2:servers:{TTT2_COM_ID}"
    if cached := cache_get(key):
        return {int(k): v for k, v in cached.items()}
    with api_client() as client:
        tree = get_server_world_tree(client, TTT2_COM_ID)
    cache_set(key, {str(k): v for k, v in tree.items()}, get_settings().cache_ttl_servers)
    return tree


@router.get("/servers", summary="Server and world list")
def servers():
    """Return the server → world hierarchy."""
    return {str(k): v for k, v in _get_world_tree().items()}


@router.get("/rooms", summary="Active rooms")
def rooms():
    """Return all active rooms across every world."""
    key = f"ttt2:rooms:{TTT2_COM_ID}"
    if cached := cache_get(key):
        return cached
    all_worlds = _get_all_worlds()
    with api_client() as client:
        result = get_rooms(client, TTT2_COM_ID, all_worlds)
    cache_set(key, jsonable_encoder(result), get_settings().cache_ttl_rooms)
    return result


def _fetch_rooms_all():
    """Blocking helper: fetch rooms from RPCN and apply matchmaking logic."""
    all_worlds = _get_all_worlds()
    with api_client() as client:
        result = get_rooms_all(client, TTT2_COM_ID, all_worlds)

    all_room_dtos = result["player_match"] + result["rank_match"]
    phantom_rooms = update_and_get_matchmaking(all_room_dtos)
    result["rank_match"].extend(phantom_rooms)
    return result, all_room_dtos


@router.get("/rooms/all", summary="All rooms including hidden")
async def rooms_all():
    """Search all rooms including hidden ones via SearchRoomAll."""
    key = f"ttt2:rooms_all:{TTT2_COM_ID}"
    if cached := cache_get(key):
        return cached

    result, all_room_dtos = await asyncio.to_thread(_fetch_rooms_all)

    # Record activity to DynamoDB (fire-and-forget on error)
    try:
        player_npids = []
        total_players = 0
        for room in all_room_dtos:
            total_players += room.current_members
            if room.owner_npid:
                player_npids.append(room.owner_npid)
            for user in room.users:
                if hasattr(user, "user_id") and user.user_id != room.owner_npid:
                    player_npids.append(user.user_id)
        await activity_tracker.record_activity(player_npids, total_players)
    except Exception:
        logger.warning("Failed to record activity", exc_info=True)

    encoded = jsonable_encoder(result)
    cache_set(key, encoded, get_settings().cache_ttl_rooms_all)
    return encoded


@router.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
    board: int = Query(default=TTT2_RANK_BOARD_ID, description="Score board ID"),
    top: int = Query(default=10, ge=1, le=100, description="Number of entries to return"),
):
    """Return the top N leaderboard entries with TTT2 character info decoded."""
    key = f"ttt2:leaderboard:{TTT2_COM_ID}:{board}:{top}"
    if cached := cache_get(key):
        return cached
    with api_client() as client:
        lb = get_leaderboard(client, TTT2_COM_ID, board, num_ranks=top)
    cache_set(key, jsonable_encoder(lb), get_settings().cache_ttl_leaderboard)
    return lb


@router.get("/stats/activity", summary="Hourly player activity (KST)")
async def stats_activity():
    """Return average player count per KST hour (0-23) over the last 7 days."""
    key = f"ttt2:stats_activity:{TTT2_COM_ID}"
    if cached := cache_get(key):
        return cached
    result = await activity_tracker.get_global_activity()
    cache_set(key, result, get_settings().cache_ttl_rooms)
    return result


@router.get("/players/{npid}", summary="Player lookup")
async def player_lookup(npid: str = Path(description="Player NPID")):
    """Look up a player: online status, leaderboard stats, and usual playing hours."""
    result = await lookup_player(npid)
    return jsonable_encoder(result)
