"""Domain event types for the matching module."""

from dataclasses import dataclass

from matching.models import RoomType


@dataclass
class MatchmakingDetected:
	"""A player entered matchmaking (their RANK_MATCH room disappeared)."""
	npid: str
	room_type: RoomType
	timestamp: float


@dataclass
class MatchmakingResolved:
	"""A player left matchmaking."""
	npid: str
	reason: str  # "found_opponent" | "rejoined_room" | "expired"
	timestamp: float
