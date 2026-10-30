"""The rank event's public board."""

from fastapi import APIRouter, Depends, Path

from event import models
from event.dependencies import event_service
from event.service import EventService

router = APIRouter(prefix="/event", tags=["Event"])


@router.get("", response_model=models.EventBoardOut)
async def board(service: EventService = Depends(event_service)):
    """Who holds a condition now, furthest climb first."""
    return await service.board()


@router.get("/players/{npid}", response_model=models.EventPlayerOut)
async def player(
    npid: str = Path(min_length=1, max_length=64, description="Player NPID"),
    service: EventService = Depends(event_service),
):
    """One player's starting ranks, targets and progress."""
    return await service.player(npid)
