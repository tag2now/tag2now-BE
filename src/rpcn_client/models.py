from dataclasses import dataclass
from datetime import datetime, timezone

def _format_epoch(epoch_us: int) -> str:
	"""Convert a microsecond epoch timestamp to a readable UTC datetime string."""
	if epoch_us == 0:
		return "N/A"
	try:
		dt = datetime.fromtimestamp(epoch_us / 1_000_000, tz=timezone.utc)
		return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
	except (OSError, ValueError):
		return f"epoch={epoch_us}"


@dataclass
class UserInfo:
	online_name: str
	avatar_url: str
	user_id: int

	def __str__(self):
		return f"online_name={self.online_name!r}, avatar_url={self.avatar_url!r}, user_id={self.user_id}"


@dataclass
class RoomAttr:
	id: int
	value: int

@dataclass
class RoomBinAttr:
	id: int
	data: bytes

@dataclass
class RoomInfo:
	room_id: int
	owner_npid: str
	owner_online_name: str
	current_members: int
	max_slots: int
	flag_attr: int
	int_attrs: list  # list[RoomAttr]
	bin_search_attrs: list  # list[RoomBinAttr]
	bin_attrs: list  # list[RoomBinAttr]
	users: list[UserInfo]

	@classmethod
	def from_response_room(cls, room):
		return cls(
			room_id=room.roomId,
			owner_npid=room.owner.npId if room.owner else "",
			owner_online_name=room.owner.onlineName if room.owner else "",
			current_members=room.curMemberNum.value,
			max_slots=room.maxSlot.value,
			flag_attr=room.flagAttr,
			int_attrs=[RoomAttr(id=a.id.value, value=a.num) for a in room.roomSearchableIntAttrExternal],
			bin_search_attrs=[RoomBinAttr(id=a.id.value, data=a.data) for a in room.roomSearchableBinAttrExternal],
			bin_attrs=[RoomBinAttr(id=a.id.value, data=a.data) for a in room.roomBinAttrExternal],
			users=[UserInfo(user_id=ru.userInfo.npId,
							online_name=ru.userInfo.onlineName,
							avatar_url=ru.userInfo.avatarUrl)
				   for ru in getattr(room, 'users', [])]
		)

	def __str__(self):
		base = f"Room {self.room_id}: {self.current_members}/{self.max_slots} players, owner={self.owner_npid or '?'} ({self.owner_online_name})"
		parts = [base]
		if self.flag_attr:
			parts.append(f"  flagAttr=0x{self.flag_attr:08x}")
		for a in self.int_attrs:
			parts.append(f"  IntAttr[{a.id}] = {a.value}")
		for a in self.bin_search_attrs:
			parts.append(f"  BinSearchAttr[{a.id}] = {a.data.hex()}")
		for a in self.bin_attrs:
			parts.append(f"  BinAttr[{a.id}] = {a.data.hex()}")
		return "\n".join(parts)

@dataclass
class SearchRoomsResult:
	total: int
	rooms: list  # list[RoomInfo]

	def __str__(self):
		lines = [f"{self.total} room(s)"]
		for room in self.rooms:
			lines.append(f"  {room}")
		return "\n".join(lines)

@dataclass
class ScoreEntry:
	rank: int
	np_id: str
	online_name: str
	score: int
	pc_id: int
	record_date: int
	has_game_data: bool
	comment: str
	game_info: bytes

	def __str__(self):
		lines = [
			f"#{self.rank:4d}  npId: {self.np_id:<20s}  online: {self.online_name or '(none)'}",
			f"       score={self.score}  pcId={self.pc_id}  "
			f"recorded={_format_epoch(self.record_date)}  hasGameData={self.has_game_data}",
		]
		if self.comment:
			lines.append(f'       comment: "{self.comment}"')
		if self.game_info:
			lines.append(f"       gameInfo ({len(self.game_info)} bytes):")
			for off in range(0, len(self.game_info), 16):
				chunk = self.game_info[off:off + 16]
				hex_part = " ".join(f"{b:02x}" for b in chunk)
				ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
				lines.append(f"         {off:04x}: {hex_part:<48s} {ascii_part}")
		return "\n".join(lines)

@dataclass
class ScoreResult:
	total_records: int
	last_sort_date: int
	entries: list  # list[ScoreEntry]

	def __str__(self):
		lines = [
			f"Total records: {self.total_records}",
			f"Last sort date: {_format_epoch(self.last_sort_date)}",
		]
		for entry in self.entries:
			lines.append(str(entry))
		return "\n".join(lines)

	@classmethod
	def from_response(cls, resp):
		entries = []
		n_comments = len(resp.commentArray)
		n_info = len(resp.infoArray)
		for i, entry in enumerate(resp.rankArray):
			comment = resp.commentArray[i] if i < n_comments else ""
			game_info = resp.infoArray[i].data if i < n_info else b""
			entries.append(ScoreEntry(
				rank=entry.rank,
				np_id=entry.npId,
				online_name=entry.onlineName,
				score=entry.score,
				pc_id=entry.pcId,
				record_date=entry.recordDate,
				has_game_data=entry.hasGameData,
				comment=comment,
				game_info=game_info,
			))
		return cls(
			total_records=resp.totalRecord,
			last_sort_date=resp.lastSortDate,
			entries=entries,
		)