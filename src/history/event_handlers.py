"""Event handlers that connect the history module to domain events."""

import logging
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

from history.models import RankMatchSnapshotRecord
from matching.models import RoomType
from shared.events import subscribe

logger = logging.getLogger(__name__)

_prev_gaming_room_ids: set[int] = set()


def _to_snapshot_record(room) -> RankMatchSnapshotRecord:
	u1 = room.users[0] if len(room.users) > 0 else None
	u2 = room.users[1] if len(room.users) > 1 else None
	return RankMatchSnapshotRecord(
		room_id=room.room_id,
		rank_id=room.rank_info.id,
		user1_npid=u1.npid if u1 else "",
		user1_online_name=u1.online_name if u1 else "",
		user2_npid=u2.npid if u2 else "",
		user2_online_name=u2.online_name if u2 else "",
		created_dt=datetime.now(KST),
	)


async def _handle_activity_snapshot(event) -> None:
	"""Handle ActivitySnapshot — convert room DTOs and persist."""
	global _prev_gaming_room_ids
	from history import service as history_service

	gaming_rooms = {
		r.room_id: r for r in event.rooms
		if r.room_type == RoomType.RANK_MATCH and r.current_members == 2
	}
	new_rooms = [r for room_id, r in gaming_rooms.items() if room_id not in _prev_gaming_room_ids]
	_prev_gaming_room_ids = set(gaming_rooms)

	if not new_rooms:
		return

	try:
		snapshots = [_to_snapshot_record(room) for room in new_rooms]
		await history_service.record_snapshot(snapshots)
	except Exception:
		logger.warning("Failed to record history snapshot", exc_info=True)


def subscribe_events() -> None:
	"""Register history handlers for domain events."""
	from matching.events import ActivitySnapshot

	subscribe(ActivitySnapshot, _handle_activity_snapshot)
	logger.info("History event handlers registered")
