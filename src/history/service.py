"""History service — cached reads and write orchestration.

The service owns sessions and transactions; the adapter only receives a session.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from history.models import (
    ActivitySnapshot,
    DailySummary,
    HourlyActivity,
    PlayerStats,
    RankMatchSnapshotRecord,
    RankRoom,
)
from history.ports import HistoryPort
from shared.cache import cache_delete_pattern, cache_get, cache_set
from shared.settings import get_settings


class HistoryService:
    def __init__(self, repo: HistoryPort, sessions: async_sessionmaker[AsyncSession]):
        self._repo = repo
        self._sessions = sessions

    # -- Write ---------------------------------------------------------------

    async def record_snapshot(self, rooms: list[RankMatchSnapshotRecord]) -> None:
        async with self._sessions() as session, session.begin():
            await self._repo.record_snapshot(session, rooms)

    async def touch_rank_matches(self, rooms: list[RankMatchSnapshotRecord], observed_at: datetime) -> None:
        if not rooms:
            return
        async with self._sessions() as session, session.begin():
            await self._repo.touch_rank_matches(session, rooms, observed_at)

    async def record_daily_matched_players(self, npids: set[str], observed_at: datetime) -> None:
        """Record participants, then invalidate summaries only after commit."""
        if not any(npids):
            return
        async with self._sessions() as session, session.begin():
            await self._repo.record_daily_matched_players(session, npids, observed_at)
        cache_delete_pattern("history:daily:*")

    async def record_activity_snapshot(self, snapshot: ActivitySnapshot) -> None:
        async with self._sessions() as session, session.begin():
            await self._repo.record_activity_snapshot(session, snapshot)
        cache_delete_pattern("history:daily:*")

    # -- Read: rank-match rooms ----------------------------------------------

    async def rank_room(self, npid: str, at: datetime) -> RankRoom | None:
        async with self._sessions() as session:
            return await self._repo.find_rank_room(session, npid, at)

    # -- Read: global stats --------------------------------------------------

    async def get_hourly_activity(self, days: int = 7) -> list[HourlyActivity]:
        key = f"history:hourly:{days}"
        if cached := cache_get(key):
            return cached
        async with self._sessions() as session:
            result = await self._repo.get_hourly_activity(session, days)
        cache_set(key, result, get_settings().cache_ttl_activity)
        return result

    async def get_daily_summary(self, days: int = 30) -> list[DailySummary]:
        key = f"history:daily:{days}"
        if cached := cache_get(key):
            return cached
        async with self._sessions() as session:
            result = await self._repo.get_daily_summary(session, days)
        cache_set(key, result, get_settings().cache_ttl_activity)
        return result

    # -- Read: per-player stats ----------------------------------------------

    async def get_player_stats(self, npid: str, days: int = 30) -> PlayerStats:
        key = f"history:player_stats:{npid}:{days}"
        if cached := cache_get(key):
            return cached
        async with self._sessions() as session:
            result = await self._repo.get_player_stats(session, npid, days)
        cache_set(key, result, get_settings().cache_ttl_player_hours)
        return result
