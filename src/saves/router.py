from fastapi import APIRouter, Path

from saves import service
from saves.models import PlayerSaveOut

router = APIRouter(prefix="/saves", tags=["Saves"])


@router.get("/players/{npid}", response_model=PlayerSaveOut)
async def player_save(npid: str = Path(min_length=1, max_length=64, description="Player NPID")):
    """A player's TTT2 save: account rank, record and the rank of every character
    they have used. Read-only, and up to ten minutes behind the game."""
    return await service.get_player_save(npid)
