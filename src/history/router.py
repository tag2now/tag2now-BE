"""FastAPI router for history and statistics endpoints."""

from fastapi import APIRouter, Path, Query

from history import service

router = APIRouter(prefix="/history", tags=["History & Statistics"])


@router.get("/stats", summary="Hourly player activity (KST)")
async def hourly_activity(
	days: int = Query(default=7, ge=1, le=90, description="Number of days to aggregate"),
):
	"""Return average and peak player counts per KST hour."""
	return await service.get_hourly_activity(days)


@router.get("/stats/daily", summary="Daily summary")
async def daily_summary(
	days: int = Query(default=30, ge=1, le=90, description="Number of days"),
):
	"""Return daily peak/average player and room counts."""
	return await service.get_daily_summary(days)


@router.get("/players/{npid}", summary="Player history")
async def player_history(
	npid: str = Path(description="Player NPID"),
	days: int = Query(default=30, ge=1, le=90, description="Number of days"),
):
	"""Return aggregated history stats for a player."""
	return await service.get_player_stats(npid, days)
