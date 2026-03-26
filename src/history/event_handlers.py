"""Event handlers that connect the history module to domain events."""

import logging

from history.models import RoomSnapshotRecord
from shared.events import subscribe

logger = logging.getLogger(__name__)


def _to_snapshot_record(room) -> RoomSnapshotRecord:
	"""Convert a RoomInfoDTO to a RoomSnapshotRecord."""
	member_npids = []
	member_names = []
	if room.owner_npid:
		member_npids.append(room.owner_npid)
		member_names.append(room.owner_online_name)
	for user in room.users:
		if hasattr(user, "user_id") and user.user_id != room.owner_npid:
			member_npids.append(user.user_id)
			member_names.append(getattr(user, "online_name", ""))
	return RoomSnapshotRecord(
		room_id=room.room_id,
		room_type=room.room_type.value,
		owner_npid=room.owner_npid,
		owner_online_name=room.owner_online_name,
		current_members=room.current_members,
		max_slots=room.max_slots,
		is_matchmaking=room.room_id == 0,
		member_npids=member_npids,
		member_online_names=member_names,
	)


async def _handle_activity_snapshot(event) -> None:
	"""Handle ActivitySnapshot — convert room DTOs and persist."""
	from history import service as history_service

	try:
		snapshots = [_to_snapshot_record(room) for room in event.rooms]
		await history_service.record_snapshot(snapshots)
	except Exception:
		logger.warning("Failed to record history snapshot", exc_info=True)


def subscribe_events() -> None:
	"""Register history handlers for domain events."""
	from matching.events import ActivitySnapshot

	subscribe(ActivitySnapshot, _handle_activity_snapshot)
	logger.info("History event handlers registered")
