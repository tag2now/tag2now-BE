"""Port interface for the history module."""

from abc import ABC, abstractmethod

from history.models import RoomSnapshotRecord


class HistoryPort(ABC):
	"""Outbound port for match history persistence and statistics."""

	@abstractmethod
	async def init(self) -> None:
		"""Initialize the backing store."""

	@abstractmethod
	async def close(self) -> None:
		"""Release resources."""

	# -- Write ---------------------------------------------------------------

	@abstractmethod
	async def record_snapshot(self, rooms: list[RoomSnapshotRecord]) -> None:
		"""Persist a room snapshot and update hourly aggregates."""

	# -- Read: global stats --------------------------------------------------

	@abstractmethod
	async def get_hourly_activity(self, days: int = 7) -> list[dict]:
		"""Return average and peak player counts per KST hour."""

	@abstractmethod
	async def get_daily_summary(self, days: int = 30) -> list[dict]:
		"""Return daily player and room totals."""

	# -- Read: per-player stats ----------------------------------------------

	@abstractmethod
	async def get_player_stats(self, npid: str, days: int = 30) -> dict:
		"""Return aggregated stats for a single player."""

	@abstractmethod
	async def get_player_hours(self, npid: str, days: int = 7) -> list[int]:
		"""Return KST hours when the player is typically online."""
