"""FastAPI router for Tekken Tag Tournament 2 endpoints."""

from fastapi import APIRouter, Depends, Query, Response

from matching.dependencies import matching_service
from matching.models import GameDataOut
from matching.service import LEADERBOARD_CACHE_SIZE, MatchingService, get_game_data, players_in, with_streams
from shared.ttt2 import TTT2_COM_ID, TTT2_RANK_BOARD_ID
from streaming.dependencies import streaming_service
from streaming.service import StreamingService

router = APIRouter(tags=["Tekken Tag Tournament 2"])


# Changes only with a deploy, so a client may keep it for five minutes.
GAME_DATA_MAX_AGE = 300


@router.get("/game-data", response_model=GameDataOut, summary="Character and rank tables")
def game_data(response: Response):
    """Every TTT2 character id and rank code with its name; the one table other services read."""
    response.headers["Cache-Control"] = f"public, max-age={GAME_DATA_MAX_AGE}"
    return get_game_data()


@router.get("/servers", summary="Server and world list")
def servers(service: MatchingService = Depends(matching_service)):
    """Return the server → world hierarchy."""
    return service.get_server_world_tree(TTT2_COM_ID)


@router.get("/rooms/all", summary="All rooms including hidden")
async def rooms_all(
    matching: MatchingService = Depends(matching_service),
    streaming: StreamingService = Depends(streaming_service),
):
    """Search all rooms including hidden ones via SearchRoomAll, each user marked with their broadcast."""
    rooms = await matching.get_rooms_all(TTT2_COM_ID)
    live = await streaming.live_or_empty(players_in(rooms))
    return with_streams(rooms, live)


@router.get("/leaderboard", summary="Leaderboard entries")
def leaderboard(
    board: int = Query(default=TTT2_RANK_BOARD_ID, description="Score board ID"),
    top: int = Query(default=10, ge=1, le=LEADERBOARD_CACHE_SIZE),
    service: MatchingService = Depends(matching_service),
):
    """Return the top N leaderboard entries with TTT2 character info decoded."""
    return service.get_leaderboard(TTT2_COM_ID, board, num_ranks=top)
