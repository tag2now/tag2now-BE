"""TTT2 business logic functions."""

import struct

from rpcn_client import RpcnClient, RpcnError, ScoreEntry
from shared.cache import cache_get
from tekken_tt2 import activity_tracker
from tekken_tt2.models import (
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


def get_server_world_tree(client: RpcnClient, com_id: str) -> dict[int, list[int]]:
	"""Fetch the server → world hierarchy.  Returns {server_id: [world_ids]}."""
	servers = client.get_server_list(com_id)
	tree = {}
	for server_id in servers:
		tree[server_id] = client.get_world_list(com_id, server_id)
	return tree


def _group_rooms_by_type(rooms: list[RoomInfoDTO]) -> dict[str, list[RoomInfoDTO]]:
	grouped: dict[str, list[RoomInfoDTO]] = {RoomType.PLAYER_MATCH.value: [], RoomType.RANK_MATCH.value: []}
	for room in rooms:
		grouped[room.room_type.value].append(room)
	return grouped


def get_rooms(client: RpcnClient, com_id: str, worlds: list[int]) -> dict[str, list[RoomInfoDTO]]:
	"""Search active rooms across all worlds. Returns rooms grouped by type."""
	all_rooms: list[RoomInfoDTO] = []
	for world_id in worlds:
		try:
			resp = client.search_rooms(com_id, world_id=world_id, max_results=20)
			if resp.total > 0:
				all_rooms.extend(RoomInfoDTO(room) for room in resp.rooms)
		except RpcnError:
			pass
	return _group_rooms_by_type(all_rooms)


def get_rooms_all(client: RpcnClient, com_id: str, worlds: list[int]) -> dict[str, list[RoomInfoDTO]]:
	"""Search all rooms (including hidden) across all worlds. Returns rooms grouped by type."""
	# TODO rpcs 에서 방 search 시 잠시 방 나가지는 현상을 고려해서 캐싱 해야함
	all_rooms: list[RoomInfoDTO] = []
	for world_id in worlds:
		try:
			resp = client.search_rooms_all(com_id, world_id=world_id)
			if resp.total > 0:
				all_rooms.extend(RoomInfoDTO(room) for room in resp.rooms)
		except RpcnError:
			pass
	return _group_rooms_by_type(all_rooms)


def get_leaderboard(client: RpcnClient, com_id: str, board_id: int, num_ranks: int = 10) -> TTT2LeaderboardResult:
	"""Fetch the top N leaderboard entries with parsed TTT2 game_info."""
	result = client.get_score_range(
		com_id, board_id,
		start_rank=1, num_ranks=num_ranks,
		with_comment=True, with_game_info=True,
	)
	entries = [
		TTT2LeaderboardEntry(
			rank=e.rank, np_id=e.np_id, online_name=e.online_name,
			score=e.score, pc_id=e.pc_id, record_date=e.record_date,
			has_game_data=e.has_game_data, comment=e.comment,
			player_info=parse_game_info(e.game_info) if e.game_info else None,
		)
		for e in result.entries
	]
	return TTT2LeaderboardResult(
		total_records=result.total_records,
		last_sort_date=result.last_sort_date,
		entries=entries,
	)


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
					# Phantom rooms (matchmaking) have room_id=0
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

	# 3. Usual playing hours from DynamoDB
	usual_hours = await activity_tracker.get_player_hours(npid)

	return PlayerLookupResponse(
		npid=npid,
		online_status=online_status,
		leaderboard=lb_entry,
		usual_playing_hours_kst=usual_hours,
	)
