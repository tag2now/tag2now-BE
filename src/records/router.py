"""Recorded rank matches, read-only and public."""

from fastapi import APIRouter, Depends, Query

from records.dependencies import records_service
from records.models import MatchRecordPageOut, OpponentRecord, WeeklyPlayer
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


@router.get("/opponents", response_model=list[OpponentRecord])
async def frequent_opponents(
    npid: str = Query(min_length=1, max_length=64, description="The player whose opponents to answer"),
    days: int = Query(30, ge=1, le=90, description="How many days back to count"),
    service: RecordsService = Depends(records_service),
):
    """The four opponents a player met most, with the player's wins and losses against each.
    Only matches the player's own save showed are counted."""
    return await service.frequent_opponents(npid, days)
