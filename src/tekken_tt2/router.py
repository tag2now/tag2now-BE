"""FastAPI router for Tekken Tag Tournament 2 endpoints."""

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from shared.cache import cache_get, cache_set
from tekken_tt2.rpcn_lifecycle import api_client
from tekken_tt2.models import TTT2_COM_ID, TTT2_RANK_BOARD_ID
from tekken_tt2.service import get_server_world_tree, get_rooms, get_rooms_all, get_leaderboard
from shared.settings import get_settings

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


@router.get("/rooms/all", summary="All rooms including hidden")
def rooms_all():
    """Search all rooms including hidden ones via SearchRoomAll."""
    key = f"ttt2:rooms_all:{TTT2_COM_ID}"
    if cached := cache_get(key):
        return cached
    all_worlds = _get_all_worlds()
    with api_client() as client:
        result = get_rooms_all(client, TTT2_COM_ID, all_worlds)
    cache_set(key, jsonable_encoder(result), get_settings().cache_ttl_rooms_all)
    return result


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
