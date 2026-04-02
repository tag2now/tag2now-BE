"""History service — cached reads and write orchestration.

The service layer owns session lifecycle and transactions via decorators.
The adapter is a pure data-access layer that receives a session.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from history.db import get_history_repo
from history.models import DailySummary, HourlyActivity, PlayerStats, RankMatchSnapshotRecord, TopPlayer
from shared.cache import cache_get, cache_set
from shared.database import transactional, read_only
from shared.settings import get_settings

logger = logging.getLogger(__name__)


# -- Write -------------------------------------------------------------------

@transactional
async def record_snapshot(session: AsyncSession, rooms: list[RankMatchSnapshotRecord]) -> None:
	"""Persist a room snapshot (fire-and-forget safe)."""
	await get_history_repo().record_snapshot(session, rooms)


# -- Read: global stats ------------------------------------------------------

async def get_hourly_activity(days: int = 7) -> list[HourlyActivity]:
	key = f"history:hourly:{days}"
	if cached := cache_get(key):
		return cached
	result = await _get_hourly_activity(days)
	cache_set(key, result, get_settings().cache_ttl_activity)
	return result


@read_only
async def _get_hourly_activity(session: AsyncSession, days: int) -> list[HourlyActivity]:
	return await get_history_repo().get_hourly_activity(session, days)


async def get_daily_summary(days: int = 30) -> list[DailySummary]:
	key = f"history:daily:{days}"
	if cached := cache_get(key):
		return cached
	result = await _get_daily_summary(days)
	cache_set(key, result, get_settings().cache_ttl_activity)
	return result


@read_only
async def _get_daily_summary(session: AsyncSession, days: int) -> list[DailySummary]:
	return await get_history_repo().get_daily_summary(session, days)


# -- Read: weekly top players ------------------------------------------------

async def get_weekly_top_players(limit: int = 10) -> list[TopPlayer]:
	key = f"history:weekly_top:{limit}"
	if cached := cache_get(key):
		return cached
	result = await _get_weekly_top_players(limit)
	cache_set(key, result, get_settings().cache_ttl_activity)
	return result


@read_only
async def _get_weekly_top_players(session: AsyncSession, limit: int) -> list[TopPlayer]:
	return await get_history_repo().get_weekly_top_players(session, limit)


# -- Read: per-player stats --------------------------------------------------

async def get_player_stats(npid: str, days: int = 30) -> PlayerStats:
	key = f"history:player_stats:{npid}:{days}"
	if cached := cache_get(key):
		return cached
	result = await _get_player_stats(npid, days)
	cache_set(key, result, get_settings().cache_ttl_player_hours)
	return result


@read_only
async def _get_player_stats(session: AsyncSession, npid: str, days: int) -> PlayerStats:
	return await get_history_repo().get_player_stats(session, npid, days)


