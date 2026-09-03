"""Port interface for the history module."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime

from history.models import ActivitySnapshot, DailySummary, HourlyActivity, PlayerStats, RankMatchSnapshotRecord, TopPlayer


class HistoryPort(ABC):
	"""Outbound port for match history persistence and statistics."""

	# -- Write ---------------------------------------------------------------

	@abstractmethod
	async def record_snapshot(self, session: AsyncSession, rooms: list[RankMatchSnapshotRecord]) -> None:
		"""Persist a room snapshot and update hourly aggregates."""

	@abstractmethod
	async def record_daily_matched_players(self, session: AsyncSession, npids: set[str], observed_at: datetime) -> None:
		"""Persist unique completed-rank-match participants for the KST day."""

	@abstractmethod
	async def record_activity_snapshot(self, session: AsyncSession, snapshot: ActivitySnapshot) -> None:
		"""Persist one observed concurrent-player snapshot."""

	# -- Read: global stats --------------------------------------------------

	@abstractmethod
	async def get_hourly_activity(self, session: AsyncSession, days: int = 7) -> list[HourlyActivity]:
		"""Return average and peak player counts per KST hour."""

	@abstractmethod
	async def get_daily_summary(self, session: AsyncSession, days: int = 30) -> list[DailySummary]:
		"""Return daily player and room totals."""

	# -- Read: per-player stats ----------------------------------------------

	@abstractmethod
	async def get_player_stats(self, session: AsyncSession, npid: str, days: int = 30) -> PlayerStats:
		"""Return aggregated stats for a single player."""

	@abstractmethod
	async def get_weekly_top_players(self, session: AsyncSession, limit: int = 10) -> list[TopPlayer]:
		"""Return the top N most frequently seen players in the last 7 days."""
