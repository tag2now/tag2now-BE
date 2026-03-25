"""Detect matchmaking players by diffing consecutive room snapshots.

Players cycling through the TTT2 matchmaking loop (searchRoom → createRoom →
wait → quit) are only visible while their solo room exists.  By comparing
snapshots we can infer that a player whose 1-member room disappeared is still
actively searching.
"""

import time
from dataclasses import dataclass

from shared.settings import get_settings
from tekken_tt2.models import Rank, RoomInfoDTO, RoomType


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
_matchmaking_players: dict[str, _MatchmakingPlayer] = {}


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
		)
		for room in current_rooms
	}

	if not _prev_rooms:
		_prev_rooms = current
		return []

	prev_keys = set(_prev_rooms)
	curr_keys = set(current)

	# Rooms that disappeared — if they had 1 member, owner was matchmaking
	for room_id in prev_keys - curr_keys:
		prev = _prev_rooms[room_id]
		if prev.room_type == RoomType.RANK_MATCH and not prev.is_gaming():
			existing = _matchmaking_players.get(prev.owner_npid)
			_matchmaking_players[prev.owner_npid] = _MatchmakingPlayer(
				npid=prev.owner_npid,
				online_name=prev.owner_online_name,
				room_type=RoomType.RANK_MATCH,
				rank_info=prev.rank_info,
				last_seen=now,
				first_searching=existing.first_searching if existing else now,
			)

	# Rooms that persisted gaming — owner found an opponent
	for room_id in prev_keys & curr_keys:
		cur = current[room_id]
		if cur.is_gaming():
			_matchmaking_players.pop(cur.owner_npid, None)

	# Players currently in a room are not matchmaking
	active_npids = {room.owner_npid for room in current.values()}
	for npid in list(_matchmaking_players):
		if npid in active_npids:
			_matchmaking_players.pop(npid)

	# Evict stale entries
	ttl = get_settings().matchmaking_ttl
	for npid in list(_matchmaking_players):
		if now - _matchmaking_players[npid].last_seen > ttl:
			del _matchmaking_players[npid]

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
