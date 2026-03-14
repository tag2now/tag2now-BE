"""TTT2 dataclasses and game constants."""

from dataclasses import dataclass, field

from rpcn_client import RoomInfo
from tekken_tt2.data import TTT2_CHARACTERS

# ---------------------------------------------------------------------------
# Game constants
# ---------------------------------------------------------------------------

TTT2_COM_ID = "NPWR02973_00"
TTT2_BOARD_ID = 0

_GAME_INFO_FMT = ">4B4I"
_GAME_INFO_SIZE = 20


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CharInfo:
	"""A single character's stats from a TTT2 leaderboard entry."""
	char_id: int
	rank: int
	wins: int
	losses: int
	name: str = field(init=False)

	def __post_init__(self):
		self.name = TTT2_CHARACTERS.get(self.char_id, f"Unknown(0x{self.char_id:02x})")

	def __str__(self):
		return f"{self.name}/{hex(self.char_id)}(rank {self.rank}) {self.wins}W/{self.losses}L"


@dataclass
class TTT2GameInfo:
	"""Parsed TTT2 game_info from a 64-byte leaderboard blob."""
	main_char_info: CharInfo
	sub_char_info: CharInfo

	def __str__(self):
		return f"{self.main_char_info} + {self.sub_char_info}"


@dataclass
class TTT2LeaderboardEntry:
	"""A leaderboard entry with game_info already parsed into TTT2GameInfo."""
	rank: int
	np_id: str
	online_name: str
	score: int
	pc_id: int
	record_date: int
	has_game_data: bool
	comment: str
	player_info: TTT2GameInfo | None

	def __str__(self):
		base = f"#{self.rank} {self.online_name} ({self.np_id}) score={self.score}"
		if self.player_info:
			base += f"\n       >> {self.player_info}"
		return base


@dataclass
class TTT2LeaderboardResult:
	"""Leaderboard result with parsed TTT2-specific entries."""
	total_records: int
	last_sort_date: int
	entries: list[TTT2LeaderboardEntry]

@dataclass
class RoomInfoDTO:
	room_id: int
	owner_npid: str
	owner_online_name: str
	max_slots: int
	rank: int
	users: list

	def __init__(self, room_info: RoomInfo):
		self.room_id = room_info.room_id
		self.owner_npid = room_info.owner_npid
		self.owner_online_name = room_info.owner_online_name
		self.max_slots = room_info.max_slots
		self.users = room_info.users

		self.rank = room_info.int_attrs[4].value - 7
