"""Data models for the history module."""

from dataclasses import dataclass, field
from datetime import datetime


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


@dataclass
class HourlyActivity:
	"""Average and peak player counts for a single KST hour."""
	hour: int
	avg_players: float
	peak_players: int


@dataclass
class DailySummary:
	"""Daily aggregated player and room statistics."""
	date: str
	peak_players: int
	avg_players: float
	peak_rooms: int


@dataclass
class TopPlayer:
    """A player ranked by how often they appeared in snapshots."""
    npid: str
    online_name: str
    match_count: int


@dataclass
class CoPlayer:
	"""A player who frequently shared rooms with the queried player."""
	npid: str
	online_name: str
	times_together: int


@dataclass
class PlayerStats:
	"""Aggregated history stats for a single player."""
	npid: str
	days_active: int
	times_seen: int
	first_seen: datetime | None
	last_seen: datetime | None
	room_type_counts: dict[str, int] = field(default_factory=dict)
	top_played_with: list[CoPlayer] = field(default_factory=list)
