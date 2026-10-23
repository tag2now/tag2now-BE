"""TTT2 application service — orchestrates ports, caching, and domain logic."""

import asyncio

from fastapi.encoders import jsonable_encoder

from shared.cache import cache_get, cache_set
from shared.settings import get_settings
from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS
from matching.matchmaking_tracker import MatchmakingTracker
from matching.models import (
    RoomInfoDTO,
    ActivityObservation,
    RoomType,
)
from matching.ports import GameServerPort

# The leaderboard is fetched once at this size and cached; every request slices from it.
LEADERBOARD_CACHE_SIZE = 500


# ---------------------------------------------------------------------------
# Pure domain functions
# ---------------------------------------------------------------------------

def _group_rooms_by_type(rooms: list[RoomInfoDTO]) -> dict[str, list[RoomInfoDTO]]:
    grouped: dict[str, list[RoomInfoDTO]] = {RoomType.PLAYER_MATCH.value: [], RoomType.RANK_MATCH.value: []}
    for room in rooms:
        grouped[room.room_type.value].append(room)
    return grouped


def get_game_data() -> dict:
    """Character and rank tables; tag2now-save-admin reads them from here."""
    return {
        "characters": [{"id": i, "name": name} for i, name in sorted(TTT2_CHARACTERS.items())],
        "ranks": [{"id": i, **rank} for i, rank in sorted(TEKKEN_RANKS.items())],
    }


def players_in(groups: dict) -> set[str]:
    """Every npid in a room list as get_rooms_all answers it."""
    return {user["npid"] for rooms in groups.values() for room in rooms for user in room["users"] if user.get("npid")}


def with_streams(groups: dict, live: dict[str, dict]) -> dict:
    """The room list with each user's `stream` set to their broadcast, or None.

    `live` is keyed by lower-cased npid, as StreamingService.live_for answers it.
    """
    def user_with_stream(user: dict) -> dict:
        return {**user, "stream": live.get((user.get("npid") or "").lower())}

    return {group: [{**room, "users": [user_with_stream(u) for u in room["users"]]} for room in rooms]
            for group, rooms in groups.items()}


def _leaderboard_cache_key(com_id: str, board_id: int) -> str:
    return f"ttt2:leaderboard:{com_id}:{board_id}"


def _without_excluded(lb: dict) -> dict:
    """Drop excluded accounts; those below move up past them, and ties stay tied."""
    settings = get_settings()
    excluded_ranks = [e["rank"] for e in lb["entries"] if settings.is_ranking_excluded(e["np_id"])]
    entries = [
        {**e, "rank": e["rank"] - sum(r < e["rank"] for r in excluded_ranks)}
        for e in lb["entries"] if not settings.is_ranking_excluded(e["np_id"])
    ]
    return {**lb, "total_records": lb["total_records"] - len(excluded_ranks), "entries": entries}


# ---------------------------------------------------------------------------
# Cached application service
# ---------------------------------------------------------------------------

class MatchingService:
    def __init__(self, game_server: GameServerPort, tracker: MatchmakingTracker | None = None):
        self._game_server = game_server
        self._tracker = tracker or MatchmakingTracker()

    def get_server_world_tree(self, com_id: str) -> dict[str, list[int]]:
        """Return {server_id_str: [world_ids]}, cached."""
        key = f"ttt2:servers:{com_id}"
        if cached := cache_get(key):
            return cached
        tree = self._game_server.get_server_world_tree(com_id)
        serializable = {str(k): v for k, v in tree.items()}
        cache_set(key, serializable, get_settings().cache_ttl_servers)
        return serializable

    def _get_all_worlds(self, com_id: str) -> list[int]:
        tree = self.get_server_world_tree(com_id)
        return [w for worlds in tree.values() for w in worlds]

    def _fetch_rooms_all(self, com_id: str):
        """Blocking: fetch all rooms and apply matchmaking detection."""
        rooms = self._game_server.search_rooms_all(com_id, self._get_all_worlds(com_id))
        grouped = _group_rooms_by_type(rooms)

        all_room_dtos = grouped[RoomType.PLAYER_MATCH.value] + grouped[RoomType.RANK_MATCH.value]
        phantom_rooms = self._tracker.update_and_get_phantoms(all_room_dtos)
        grouped[RoomType.RANK_MATCH.value].extend(phantom_rooms)
        grouped[RoomType.RANK_MATCH.value].sort(key=lambda r: r.rank_info.id if r.rank_info else -1)
        return grouped

    def _fetch_activity_observation(self, com_id: str) -> ActivityObservation:
        """Blocking RPCN read used by the independent history collector.

        This deliberately bypasses the HTTP response cache: collection must not
        depend on a visitor requesting the rooms endpoint.
        """
        rooms = self._game_server.search_rooms_all(com_id, self._get_all_worlds(com_id))
        rank_rooms = [room for room in rooms if room.room_type == RoomType.RANK_MATCH and room.current_members >= 1]
        return ActivityObservation(
            rank_player_npids={user.npid for room in rank_rooms for user in room.users if user.npid},
            total_players=sum(len(room.users) for room in rooms), total_rooms=len(rooms),
            rank_players=sum(len(room.users) for room in rank_rooms), rank_rooms=len(rank_rooms),
            rank_matches=[room for room in rank_rooms if room.current_members == 2],
        )

    async def collect_activity_observation(self, com_id: str) -> ActivityObservation:
        """Fetch current player counts and rank participants without caching."""
        return await asyncio.to_thread(self._fetch_activity_observation, com_id)

    async def get_rooms_all(self, com_id: str) -> dict:
        """Search all rooms including hidden, with matchmaking detection. Cached."""
        key = f"ttt2:rooms_all:{com_id}"
        if cached := cache_get(key):
            return cached

        result = await asyncio.to_thread(self._fetch_rooms_all, com_id)
        encoded = jsonable_encoder(result)
        cache_set(key, encoded, get_settings().cache_ttl_rooms_all)
        return encoded

    def get_leaderboard(self, com_id: str, board_id: int, num_ranks: int) -> dict:
        """Return the top N entries, sliced from the single cached full leaderboard."""
        full = self._get_full_leaderboard(com_id, board_id)
        return {**full, "entries": full["entries"][:num_ranks]}

    def _get_full_leaderboard(self, com_id: str, board_id: int) -> dict:
        """Fetch the full leaderboard, cached under one key regardless of requested size."""
        key = _leaderboard_cache_key(com_id, board_id)
        if cached := cache_get(key):
            return cached
        lb = self._game_server.get_leaderboard(com_id, board_id, LEADERBOARD_CACHE_SIZE)
        encoded = _without_excluded(jsonable_encoder(lb))
        cache_set(key, encoded, get_settings().cache_ttl_leaderboard)
        return encoded
