"""TTT2 application service — orchestrates ports, caching, and domain logic."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi.encoders import jsonable_encoder

from matching.events import ActivitySnapshot
from shared.cache import cache_get, cache_set
from shared.events import publish
from shared.settings import get_settings
from matching.db import get_game_server_repo
from matching.matchmaking_tracker import update_and_get_matchmaking
from matching.models import (
	PlayerLookupResponse,
	PlayerOnlineStatus,
	RoomInfoDTO,
	RoomType,
	TTT2_COM_ID,
	TTT2_RANK_BOARD_ID,
	TTT2LeaderboardEntry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure domain functions
# ---------------------------------------------------------------------------

def _group_rooms_by_type(rooms: list[RoomInfoDTO]) -> dict[str, list[RoomInfoDTO]]:
	grouped: dict[str, list[RoomInfoDTO]] = {RoomType.PLAYER_MATCH.value: [], RoomType.RANK_MATCH.value: []}
	for room in rooms:
		grouped[room.room_type.value].append(room)
	return grouped


# ---------------------------------------------------------------------------
# Cached application services
# ---------------------------------------------------------------------------

def get_server_world_tree(com_id: str) -> dict[str, list[int]]:
	"""Return {server_id_str: [world_ids]}, cached."""
	key = f"ttt2:servers:{com_id}"
	if cached := cache_get(key):
		return cached
	repo = get_game_server_repo()
	tree = repo.get_server_world_tree(com_id)
	serializable = {str(k): v for k, v in tree.items()}
	cache_set(key, serializable, get_settings().cache_ttl_servers)
	return serializable


def _get_all_worlds(com_id: str) -> list[int]:
	tree = get_server_world_tree(com_id)
	return [w for worlds in tree.values() for w in worlds]


def get_rooms(com_id: str) -> dict:
	"""Search active rooms, cached."""
	key = f"ttt2:rooms:{com_id}"
	if cached := cache_get(key):
		return cached
	repo = get_game_server_repo()
	rooms = repo.search_rooms(com_id, _get_all_worlds(com_id))
	result = jsonable_encoder(_group_rooms_by_type(rooms))
	cache_set(key, result, get_settings().cache_ttl_rooms)
	return result


def _fetch_rooms_all(com_id: str):
	"""Blocking: fetch all rooms and apply matchmaking detection."""
	repo = get_game_server_repo()
	rooms = repo.search_rooms_all(com_id, _get_all_worlds(com_id))
	grouped = _group_rooms_by_type(rooms)

	all_room_dtos = grouped[RoomType.PLAYER_MATCH.value] + grouped[RoomType.RANK_MATCH.value]
	phantom_rooms = update_and_get_matchmaking(all_room_dtos)
	grouped[RoomType.RANK_MATCH.value].extend(phantom_rooms)
	grouped[RoomType.RANK_MATCH.value].sort(key=lambda r: r.rank_info.id)
	return grouped, all_room_dtos


async def get_rooms_all(com_id: str) -> dict:
	"""Search all rooms including hidden, with matchmaking detection. Cached."""
	key = f"ttt2:rooms_all:{com_id}"
	if cached := cache_get(key):
		return cached

	result, all_room_dtos = await asyncio.to_thread(_fetch_rooms_all, com_id)

	# Publish snapshot event for history and other consumers
	publish(ActivitySnapshot(rooms=all_room_dtos))

	encoded = jsonable_encoder(result)
	cache_set(key, encoded, get_settings().cache_ttl_rooms_all)
	return encoded


def get_leaderboard(com_id: str, board_id: int, num_ranks: int) -> dict:
	"""Fetch leaderboard, cached."""
	key = f"ttt2:leaderboard:{com_id}:{board_id}:{num_ranks}"
	if cached := cache_get(key):
		return cached
	repo = get_game_server_repo()
	lb = repo.get_leaderboard(com_id, board_id, num_ranks)
	encoded = jsonable_encoder(lb)
	cache_set(key, encoded, get_settings().cache_ttl_leaderboard)
	return encoded



async def lookup_player(npid: str) -> PlayerLookupResponse:
	"""Look up a player by NPID using cached room/leaderboard data + history."""

	# 1. Online status from cached /rooms/all + last_seen from history
	from history import service as history_service
	is_matchmaking = False

	rooms_cached = cache_get(f"ttt2:rooms_all:{TTT2_COM_ID}")
	if rooms_cached:
		for room_type_key in ("player_match", "rank_match"):
			for room in rooms_cached.get(room_type_key, []):
				members = [u.get("user_id", "") for u in room.get("users", [])]
				if npid in members:
					is_matchmaking = True
					break

	player_stats = await history_service.get_player_stats(npid)
	last_seen = player_stats.last_seen
	recently_seen = last_seen is not None and (datetime.now(timezone.utc) - last_seen) < timedelta(minutes=5)
	online_status = PlayerOnlineStatus(
		is_online=is_matchmaking or recently_seen,
		is_matchmaking=is_matchmaking,
		last_seen=last_seen,
	)

	# 2. Leaderboard from cache (search across common top-N caches)
	lb_entry = None
	for top in (100, 50, 10):
		lb_cached = cache_get(f"ttt2:leaderboard:{TTT2_COM_ID}:{TTT2_RANK_BOARD_ID}:{top}")
		if lb_cached and lb_cached.get("entries"):
			for entry in lb_cached["entries"]:
				if entry.get("np_id") == npid:
					lb_entry = TTT2LeaderboardEntry.from_cache(entry)
					break
			if lb_entry:
				break

	# 3. Usual playing hours from history
	usual_hours = await history_service.get_player_hours(npid)

	return PlayerLookupResponse(
		npid=npid,
		online_status=online_status,
		leaderboard=lb_entry,
		usual_playing_hours_kst=usual_hours,
	)
