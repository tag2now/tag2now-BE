"""Recorded rank matches, read-only and public."""

from fastapi import APIRouter, Depends, Query

from records.dependencies import records_service
from records.models import MatchRecordPageOut, WeeklyPlayer
from records.service import RecordsService

router = APIRouter(prefix="/records", tags=["Records"])


@router.get("/matches", response_model=MatchRecordPageOut)
async def list_matches(
    npid: str | None = Query(None, min_length=1, max_length=64, description="Only this player's matches"),
    q: str | None = Query(
        None, min_length=1, max_length=32, description="Only matches with a player whose id or name contains this"
    ),
    before: int | None = Query(None, ge=1, description="The `next_before` of the previous page"),
    limit: int = Query(20, ge=1, le=100, description="How many matches to answer"),
    service: RecordsService = Depends(records_service),
):
    """Rank matches newest first, one each: who won with which characters at which ranks, and who lost."""
    return await service.list_matches(npid, q, before, limit)


@router.get("/weekly-top", response_model=list[WeeklyPlayer])
async def weekly_top_players(
    limit: int = Query(10, ge=1, le=50, description="How many players to answer"),
    service: RecordsService = Depends(records_service),
):
    """The players with the most rank matches in the last 7 days, with their wins and losses.
    Only matches both players' saves confirmed are counted."""
    return await service.weekly_top_players(limit)
