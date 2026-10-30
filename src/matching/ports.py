"""Port interfaces for the matching domain."""

from abc import abstractmethod

from matching.models import RoomInfoDTO, TTT2LeaderboardResult
from shared.resource import AsyncResource


class GameServerPort(AsyncResource):
    """Outbound port for game server operations."""

    @abstractmethod
    def get_server_world_tree(self, com_id: str) -> dict[int, list[int]]:
        """Return {server_id: [world_ids]} hierarchy."""

    @abstractmethod
    def search_rooms_all(self, com_id: str, worlds: list[int]) -> list[RoomInfoDTO]:
        """Search all rooms (including hidden) across given worlds."""

    @abstractmethod
    def get_leaderboard(self, com_id: str, board_id: int, num_ranks: int) -> TTT2LeaderboardResult:
        """Fetch the top N leaderboard entries with parsed game info."""
