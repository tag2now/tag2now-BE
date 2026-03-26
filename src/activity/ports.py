"""Port interface for the activity domain."""

from abc import ABC, abstractmethod


class ActivityPort(ABC):
    """Outbound port for player activity persistence."""

    @abstractmethod
    async def init(self) -> None:
        """Initialize the activity store."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the activity store."""

    @abstractmethod
    async def record_activity(self, player_npids: list[str], total_players: int) -> None:
        """Record a snapshot: global player count + each player's presence."""

    @abstractmethod
    async def get_global_activity(self) -> list[dict]:
        """Return avg player count per hour (0-23) over the retention window."""

    @abstractmethod
    async def get_player_hours(self, npid: str) -> list[int]:
        """Return hours when this player is typically online."""
