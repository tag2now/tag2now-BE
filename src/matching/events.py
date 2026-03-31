"""Domain event types for the matching module."""

from dataclasses import dataclass, field

from matching.models import RoomInfoDTO, RoomType


@dataclass
class MatchmakingDetected:
	"""A player entered matchmaking (their RANK_MATCH room disappeared)."""
	online_name: str
	room_type: RoomType
	timestamp: float


@dataclass
class MatchmakingResolved:
	"""A player left matchmaking."""
	online_name: str
	reason: str  # "found_opponent" | "rejoined_room" | "expired"
	timestamp: float


@dataclass
class ActivitySnapshot:
	"""A room snapshot was taken — contains all room DTOs for consumers."""
	rooms: list[RoomInfoDTO] = field(default_factory=list)
