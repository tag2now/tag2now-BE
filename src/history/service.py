"""History service — cached reads and write orchestration."""

import logging

from history.db import get_history_repo
from history.models import DailySummary, HourlyActivity, PlayerStats, RoomSnapshotRecord
from shared.cache import cache_get, cache_set
from shared.settings import get_settings

logger = logging.getLogger(__name__)


# -- Write -------------------------------------------------------------------

async def record_snapshot(rooms: list[RoomSnapshotRecord]) -> None:
	"""Persist a room snapshot (fire-and-forget safe)."""
	repo = get_history_repo()
	await repo.record_snapshot(rooms)


# -- Read: global stats ------------------------------------------------------

async def get_hourly_activity(days: int = 7) -> list[HourlyActivity]:
	key = f"history:hourly:{days}"
	if cached := cache_get(key):
		return cached
	repo = get_history_repo()
	result = await repo.get_hourly_activity(days)
	cache_set(key, result, get_settings().cache_ttl_activity)
	return result


async def get_daily_summary(days: int = 30) -> list[DailySummary]:
	key = f"history:daily:{days}"
	if cached := cache_get(key):
		return cached
	repo = get_history_repo()
	result = await repo.get_daily_summary(days)
	cache_set(key, result, get_settings().cache_ttl_activity)
	return result


# -- Read: per-player stats --------------------------------------------------

async def get_player_stats(npid: str, days: int = 30) -> PlayerStats:
	key = f"history:player_stats:{npid}:{days}"
	if cached := cache_get(key):
		return cached
	repo = get_history_repo()
	result = await repo.get_player_stats(npid, days)
	cache_set(key, result, get_settings().cache_ttl_player_hours)
	return result


async def get_player_hours(npid: str, days: int = 7) -> list[int]:
	key = f"history:player_hours:{npid}:{days}"
	if cached := cache_get(key):
		return cached
	repo = get_history_repo()
	result = await repo.get_player_hours(npid, days)
	cache_set(key, result, get_settings().cache_ttl_player_hours)
	return result
