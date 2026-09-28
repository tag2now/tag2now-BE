"""Infer searching players by diffing consecutive room snapshots.

A player in the TTT2 matchmaking loop is in one of three states:

- hosting   --- waiting for an opponent in their own solo RANK_MATCH room
  (createRoom); visible
- searching --- browsing other rooms without one of their own (searchRoom);
  invisible, since RPCN lists rooms and not players
- in match  --- in a two-member RANK_MATCH room; visible

A player whose RANK_MATCH room disappeared, hosting or in match, is presumed
searching. Each searching player is shown as a phantom room until they appear
in a real room again or matchmaking_ttl passes.
"""

import time
from dataclasses import dataclass

from rpcn_client import UserInfo
from shared.settings import get_settings
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

@dataclass
class _SearchingPlayer:
	npid: str
	online_name: str
	room_type: RoomType
	rank_info: Rank | None
	last_seen: float  # time.time() of the snapshot their room disappeared in


# None until the first snapshot; an empty dict is a real observation of an empty server.
_prev_rooms: dict[int, _SnapshotRoom] | None = None
_searching_players: dict[str, _SearchingPlayer] = {}  # keyed by npid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_and_get_phantoms(current_rooms: list[RoomInfoDTO]) -> list[RoomInfoDTO]:
	"""Diff current rooms against the previous snapshot; return a phantom room per searching player."""
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

	if _prev_rooms is None:
		_prev_rooms = current
		return []

	prev_keys = set(_prev_rooms)
	curr_keys = set(current)

	# A disappeared RANK_MATCH room sends everyone in it, host or both players, to searching
	for room_id in prev_keys - curr_keys:
		prev = _prev_rooms[room_id]
		if prev.room_type == RoomType.PLAYER_MATCH:
			continue

		for user in prev.users:
			_searching_players[user.npid] = _SearchingPlayer(
				npid=user.npid,
				online_name=user.online_name,
				room_type=RoomType.RANK_MATCH,
				rank_info=prev.rank_info,
				last_seen=now,
			)

	# Seen in a room again, a player is hosting (solo) or in a match (two members):
	# either way the real room shows them, so they are no longer searching
	for room in current.values():
		for user in room.users:
			_searching_players.pop(user.npid, None)

	# Unseen for matchmaking_ttl, a player has most likely left the loop
	ttl = get_settings().matchmaking_ttl
	for npid in list(_searching_players):
		mp = _searching_players[npid]
		if now - mp.last_seen > ttl:
			del _searching_players[npid]

	_prev_rooms = current

	return [
		RoomInfoDTO.phantom(
			owner_npid=mp.npid,
			owner_online_name=mp.online_name,
			room_type=mp.room_type,
			rank_info=mp.rank_info,
		)
		for mp in _searching_players.values()
	]
