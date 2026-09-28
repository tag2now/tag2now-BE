"""Independent, in-process collection of room activity, ranked participants and rank matches."""

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from history import service as history_service
from history.models import ActivitySnapshot, RankMatchSnapshotRecord
from matching.models import TTT2_COM_ID, RoomInfoDTO
from matching.service import collect_activity_observation
from shared.settings import get_settings

logger = logging.getLogger(__name__)

# Room ids of the matches in progress at the last recorded cycle, so a match is
# written once, on the cycle it first appears. A restart empties this set; the
# unique key on rank_match_snapshots catches the matches it then sees again.
_prev_rank_match_ids: set[int] = set()


def _to_snapshot_record(room: RoomInfoDTO, observed_at: datetime) -> RankMatchSnapshotRecord:
	u1 = room.users[0] if len(room.users) > 0 else None
	u2 = room.users[1] if len(room.users) > 1 else None
	return RankMatchSnapshotRecord(
		room_id=room.room_id,
		rank_id=room.rank_info.id,
		user1_npid=u1.npid if u1 else "",
		user1_online_name=u1.online_name if u1 else "",
		user2_npid=u2.npid if u2 else "",
		user2_online_name=u2.online_name if u2 else "",
		created_dt=observed_at,
	)


async def _record_new_rank_matches(rooms: list[RoomInfoDTO], observed_at: datetime) -> None:
	"""Record matches absent from the previous cycle.

	The previous set advances only after the write commits, so a failed write
	is retried on the next cycle instead of being lost.
	"""
	global _prev_rank_match_ids
	new_rooms = [room for room in rooms if room.room_id not in _prev_rank_match_ids]
	if new_rooms:
		await history_service.record_snapshot([_to_snapshot_record(room, observed_at) for room in new_rooms])
	_prev_rank_match_ids = {room.room_id for room in rooms}


async def collect_once() -> None:
	"""Store the current activity snapshot, ranked-room participants and new rank matches."""
	observed_at = datetime.now(timezone.utc)
	observation = await collect_activity_observation(TTT2_COM_ID)
	await history_service.record_daily_matched_players(observation.rank_player_npids, observed_at)
	await history_service.record_activity_snapshot(ActivitySnapshot(
		observed_at=observed_at, total_players=observation.total_players, total_rooms=observation.total_rooms,
		rank_players=observation.rank_players, rank_rooms=observation.rank_rooms,
	))
	await _record_new_rank_matches(observation.rank_matches, observed_at)


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
