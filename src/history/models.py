"""Data models for the history module."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RankMatchSnapshotRecord:
	"""Flattened room data ready for persistence."""
	room_id: int
	rank_id: int
	user1_npid: str
	user1_online_name: str
	user2_npid: str
	user2_online_name: str
	created_dt: datetime


@dataclass
class HourlyActivity:
	"""Average and peak player counts for a single KST hour."""
	hour: int
	avg_players: float
	peak_players: int


@dataclass
class DailySummary:
	"""Daily statistics, including unique completed-rank-match participants."""
	date: str
	peak_players: int | None
	avg_players: float | None
	peak_rooms: int | None
	unique_players: int = 0


@dataclass
class ActivitySnapshot:
	"""One uncached observation of all currently visible rooms."""
	observed_at: datetime
	total_players: int
	total_rooms: int
	rank_players: int
	rank_rooms: int


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
	active_hours: list[int] = field(default_factory=list)
