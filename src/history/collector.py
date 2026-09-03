"""Independent, in-process collection of room activity and ranked participants."""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from history import service as history_service
from history.models import ActivitySnapshot
from matching.models import TTT2_COM_ID
from matching.service import collect_activity_observation
from shared.settings import get_settings

logger = logging.getLogger(__name__)


async def collect_once() -> None:
	"""Store the current activity snapshot and ranked-room participant set."""
	observed_at = datetime.now(timezone.utc)
	observation = await collect_activity_observation(TTT2_COM_ID)
	await history_service.record_daily_matched_players(observation.rank_player_npids, observed_at)
	await history_service.record_activity_snapshot(ActivitySnapshot(
		observed_at=observed_at, total_players=observation.total_players, total_rooms=observation.total_rooms,
		rank_players=observation.rank_players, rank_rooms=observation.rank_rooms,
	))


async def run_collector() -> None:
	"""Run immediately, then at the configured interval until cancelled."""
	interval = get_settings().match_history_collection_interval_seconds
	while True:
		try:
			await collect_once()
		except Exception:
			logger.warning("Match-history collection failed", exc_info=True)
		await asyncio.sleep(interval)


async def stop_collector(task: asyncio.Task[None]) -> None:
	"""Cancel the background task before database dependencies are closed."""
	task.cancel()
	with contextlib.suppress(asyncio.CancelledError):
		await task
