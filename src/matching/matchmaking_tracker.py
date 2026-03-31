"""Detect matchmaking players by diffing consecutive room snapshots.

Players cycling through the TTT2 matchmaking loop (searchRoom → createRoom →
wait → quit) are only visible while their solo room exists.  By comparing
snapshots we can infer that a player whose RANK_MATCH room (1 or 2 members)
disappeared is actively searching for a match.
"""

import time
from dataclasses import dataclass

from rpcn_client import UserInfo
from shared.settings import get_settings
from matching.events import MatchmakingDetected, MatchmakingResolved
from shared.events import publish
from matching.models import Rank, RoomInfoDTO, RoomType


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

@dataclass
class _SnapshotRoom:
	room_id: int
	owner_npid: str
	owner_online_name: str
	current_members: int
	room_type: str
	rank_info: Rank | None
	users: list[UserInfo]

	def is_gaming(self) -> bool:
		return self.room_type == RoomType.RANK_MATCH and self.current_members == 2

@dataclass
class _MatchmakingPlayer:
	npid: str
	online_name: str
	room_type: RoomType
	rank_info: Rank | None
	last_seen: float       # time.time()
	first_searching: float # time.time()


_prev_rooms: dict[int, _SnapshotRoom] = {}
_matchmaking_players: dict[str, _MatchmakingPlayer] = {}  # keyed by online_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_and_get_matchmaking(current_rooms: list[RoomInfoDTO]) -> list[RoomInfoDTO]:
	"""Diff current rooms against previous snapshot, return phantom rooms for matchmaking players."""
	global _prev_rooms

	now = time.time()
	current = {
		room.room_id: _SnapshotRoom(
			room_id=room.room_id,
			owner_npid=room.owner_npid,
			owner_online_name=room.owner_online_name,
			current_members=room.current_members,
			room_type=room.room_type.value,
			rank_info=room.rank_info,
			users=room.users
		)
		for room in current_rooms
	}

	if not _prev_rooms:
		_prev_rooms = current
		return []

	prev_keys = set(_prev_rooms)
	curr_keys = set(current)

	# Disappeared RANK_MATCH rooms — all users entered matchmaking
	for room_id in prev_keys - curr_keys:
		prev = _prev_rooms[room_id]
		if prev.room_type == RoomType.PLAYER_MATCH:
			continue

		for user in prev.users:
			existing = _matchmaking_players.get(user.online_name)
			_matchmaking_players[user.online_name] = _MatchmakingPlayer(
				npid=user.online_name,
				online_name=user.online_name,
				room_type=RoomType.RANK_MATCH,
				rank_info=prev.rank_info,
				last_seen=now,
				first_searching=existing.first_searching if existing else now,
			)
			if not existing:
				publish(MatchmakingDetected(
					online_name=user.online_name,
					room_type=RoomType.RANK_MATCH, timestamp=now,
				))

	# Gaming rooms (2-member) — owner found an opponent
	for room_id in curr_keys:
		cur = current[room_id]
		if cur.owner_online_name in _matchmaking_players and cur.is_gaming():
			_matchmaking_players.pop(cur.owner_online_name)
			publish(MatchmakingResolved(online_name=cur.owner_online_name, reason="found_opponent", timestamp=now))

	# Players back in a non-gaming room are no longer matchmaking
	active_online_names = {room.owner_online_name for room in current.values() if not room.is_gaming()}
	for online_name in list(_matchmaking_players):
		if online_name in active_online_names:
			_matchmaking_players.pop(online_name)
			publish(MatchmakingResolved(online_name=online_name, reason="rejoined_room", timestamp=now))

	# Evict stale entries
	ttl = get_settings().matchmaking_ttl
	for online_name in list(_matchmaking_players):
		if now - _matchmaking_players[online_name].last_seen > ttl:
			del _matchmaking_players[online_name]
			publish(MatchmakingResolved(online_name=online_name, reason="expired", timestamp=now))

	_prev_rooms = current

	return [
		RoomInfoDTO.phantom(
			owner_npid=mp.npid,
			owner_online_name=mp.online_name,
			room_type=mp.room_type,
			rank_info=mp.rank_info,
		)
		for mp in _matchmaking_players.values()
	]
