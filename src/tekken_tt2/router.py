"""FastAPI router for Tekken Tag Tournament 2 endpoints."""

import logging

from fastapi import APIRouter, Path, Query
from fastapi.encoders import jsonable_encoder

from tekken_tt2.models import TTT2_COM_ID, TTT2_RANK_BOARD_ID
from tekken_tt2 import service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tekken Tag Tournament 2"])


@router.get("/servers", summary="Server and world list")
def servers():
    """Return the server → world hierarchy."""
    return service.get_server_world_tree(TTT2_COM_ID)


@router.get("/rooms", summary="Active rooms")
def rooms():
    """Return all active rooms across every world."""
    return service.get_rooms(TTT2_COM_ID)


@router.get("/rooms/all", summary="All rooms including hidden")
async def rooms_all():
    """Search all rooms including hidden ones via SearchRoomAll."""
    return await service.get_rooms_all(TTT2_COM_ID)


@router.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
    board: int = Query(default=TTT2_RANK_BOARD_ID, description="Score board ID"),
    top: int = Query(default=10, ge=1, le=100, description="Number of entries to return"),
):
    """Return the top N leaderboard entries with TTT2 character info decoded."""
    return service.get_leaderboard(TTT2_COM_ID, board, num_ranks=top)



@router.get("/players/{npid}", summary="Player lookup")
async def player_lookup(npid: str = Path(description="Player NPID")):
    """Look up a player: online status, leaderboard stats, and usual playing hours."""
    result = await service.lookup_player(npid)
    return jsonable_encoder(result)
