"""Data models for the history module."""

from dataclasses import dataclass, field


@dataclass
class RoomSnapshotRecord:
	"""Flattened room data ready for persistence."""

	room_id: int
	room_type: str
	owner_npid: str
	owner_online_name: str
	current_members: int
	max_slots: int
	is_matchmaking: bool
	member_npids: list[str] = field(default_factory=list)
	member_online_names: list[str] = field(default_factory=list)
