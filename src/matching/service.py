"""TTT2 application service — orchestrates ports, caching, and domain logic."""

import asyncio
import logging
import struct

from fastapi.encoders import jsonable_encoder
from rpcn_client import ScoreEntry

from activity import service as activity_service
from shared.cache import cache_get, cache_set
from shared.settings import get_settings
from matching.db import get_game_server_repo
from matching.matchmaking_tracker import update_and_get_matchmaking
from matching.models import (
	CharInfo,
	PlayerLookupResponse,
	PlayerOnlineStatus,
	Rank,
	RoomInfoDTO,
	RoomType,
	TTT2_COM_ID,
	TTT2_RANK_BOARD_ID,
	TTT2GameInfo,
	TTT2LeaderboardEntry,
	TTT2LeaderboardResult,
	_GAME_INFO_FMT,
	_GAME_INFO_SIZE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure domain functions
# ---------------------------------------------------------------------------

def parse_game_info(data: bytes) -> TTT2GameInfo | None:
	"""Parse a 64-byte TTT2 game_info blob. Returns None if data is too short."""
	if len(data) < _GAME_INFO_SIZE:
		return None
	c1_id, c2_id, c1_rank, c2_rank, c1_w, c2_w, c1_l, c2_l = struct.unpack(
		_GAME_INFO_FMT, data[:_GAME_INFO_SIZE]
	)
	return TTT2GameInfo(
		main_char_info=CharInfo(char_id=c1_id, rank_info=Rank(id=c1_rank), wins=c1_w, losses=c1_l),
		sub_char_info=CharInfo(char_id=c2_id, rank_info=Rank(id=c2_rank), wins=c2_w, losses=c2_l),
	)


def format_score_entry(entry: ScoreEntry) -> str:
	"""Format a ScoreEntry with TTT2-specific game_info decoding."""
	base = str(entry)
	if entry.game_info:
		info = parse_game_info(entry.game_info)
		if info:
			base += f"\n       >> {info}"
	return base


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
	return grouped, all_room_dtos


async def get_rooms_all(com_id: str) -> dict:
	"""Search all rooms including hidden, with matchmaking detection. Cached."""
	key = f"ttt2:rooms_all:{com_id}"
	if cached := cache_get(key):
		return cached

	result, all_room_dtos = await asyncio.to_thread(_fetch_rooms_all, com_id)

	# Record activity (fire-and-forget on error)
	try:
		player_npids = []
		total_players = 0
		for room in all_room_dtos:
			total_players += room.current_members
			if room.owner_npid:
				player_npids.append(room.owner_npid)
			for user in room.users:
				if hasattr(user, "user_id") and user.user_id != room.owner_npid:
					player_npids.append(user.user_id)
		await activity_service.record_activity(player_npids, total_players)
	except Exception:
		logger.warning("Failed to record activity", exc_info=True)

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
	"""Look up a player by NPID using cached room/leaderboard data + DynamoDB activity."""

	# 1. Online status from cached /rooms/all
	online_status = PlayerOnlineStatus(is_online=False, is_matchmaking=False)

	rooms_cached = cache_get(f"ttt2:rooms_all:{TTT2_COM_ID}")
	if rooms_cached:
		for room_type_key in ("player_match", "rank_match"):
			for room in rooms_cached.get(room_type_key, []):
				owner = room.get("owner_npid", "")
				members = [u.get("user_id", "") for u in room.get("users", [])]
				if npid == owner or npid in members:
					if room.get("room_id", 0) == 0:
						online_status = PlayerOnlineStatus(
							is_online=True,
							is_matchmaking=True,
							room_type=room_type_key,
						)
					else:
						online_status = PlayerOnlineStatus(
							is_online=True,
							is_matchmaking=False,
							room_type=room_type_key,
							room_id=room.get("room_id"),
						)
					break

	# 2. Leaderboard from cache (search across common top-N caches)
	lb_entry = None
	for top in (100, 50, 10):
		lb_cached = cache_get(f"ttt2:leaderboard:{TTT2_COM_ID}:{TTT2_RANK_BOARD_ID}:{top}")
		if lb_cached and lb_cached.get("entries"):
			for entry in lb_cached["entries"]:
				if entry.get("np_id") == npid:
					lb_entry = TTT2LeaderboardEntry(
						rank=entry["rank"],
						np_id=entry["np_id"],
						online_name=entry.get("online_name", ""),
						score=entry["score"],
						pc_id=entry.get("pc_id", 0),
						record_date=entry.get("record_date", 0),
						has_game_data=entry.get("has_game_data", False),
						comment=entry.get("comment", ""),
						player_info=None,
					)
					pi = entry.get("player_info")
					if pi:
						lb_entry.player_info = TTT2GameInfo(
							main_char_info=CharInfo(
								char_id=pi["main_char_info"]["char_id"],
								rank_info=Rank(id=pi["main_char_info"]["rank_info"]["id"]),
								wins=pi["main_char_info"]["wins"],
								losses=pi["main_char_info"]["losses"],
							),
							sub_char_info=CharInfo(
								char_id=pi["sub_char_info"]["char_id"],
								rank_info=Rank(id=pi["sub_char_info"]["rank_info"]["id"]),
								wins=pi["sub_char_info"]["wins"],
								losses=pi["sub_char_info"]["losses"],
							),
						)
					break
			if lb_entry:
				break

	# 3. Usual playing hours from activity service
	usual_hours = await activity_service.get_player_hours(npid)

	return PlayerLookupResponse(
		npid=npid,
		online_status=online_status,
		leaderboard=lb_entry,
		usual_playing_hours_kst=usual_hours,
	)
