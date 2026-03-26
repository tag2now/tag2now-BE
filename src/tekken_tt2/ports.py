"""Port interfaces for the tekken_tt2 domain."""

from abc import ABC, abstractmethod

from tekken_tt2.models import RoomInfoDTO, TTT2LeaderboardResult


class GameServerPort(ABC):
    """Outbound port for game server operations."""

    @abstractmethod
    async def init(self) -> None:
        """Initialize connection to the game server."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the game server connection."""

    @abstractmethod
    def get_server_world_tree(self, com_id: str) -> dict[int, list[int]]:
        """Return {server_id: [world_ids]} hierarchy."""

    @abstractmethod
    def search_rooms(self, com_id: str, worlds: list[int]) -> list[RoomInfoDTO]:
        """Search active rooms across given worlds."""

    @abstractmethod
    def search_rooms_all(self, com_id: str, worlds: list[int]) -> list[RoomInfoDTO]:
        """Search all rooms (including hidden) across given worlds."""

    @abstractmethod
    def get_leaderboard(self, com_id: str, board_id: int, num_ranks: int) -> TTT2LeaderboardResult:
        """Fetch the top N leaderboard entries with parsed game info."""
