"""TTT2 dataclasses."""

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel

from shared.ttt2 import TEKKEN_RANKS, TTT2_CHARACTERS

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class RoomType(str, Enum):
    PLAYER_MATCH = "player_match"
    RANK_MATCH = "rank_match"


@dataclass
class Rank:
    """A Tekken rank resolved from a numeric ID."""

    id: int
    name: str = field(init=False)
    tier: str = field(init=False)

    def __post_init__(self):
        rank_info = TEKKEN_RANKS.get(self.id, {"name": f"Unknown({self.id})", "tier": "Unknown"})
        self.name = rank_info["name"]
        self.tier = rank_info["tier"]

    def __str__(self):
        return self.name


@dataclass
class CharInfo:
    """A single character's stats from a TTT2 leaderboard entry."""

    char_id: int
    rank_info: Rank
    wins: int
    losses: int
    name: str = field(init=False)

    def __post_init__(self):
        self.name = TTT2_CHARACTERS.get(self.char_id, f"Unknown(0x{self.char_id:02x})")

    def __str__(self):
        return f"{self.name}/{hex(self.char_id)}({self.rank_info.name}) {self.wins}W/{self.losses}L"


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
class ActivityObservation:
    rank_player_npids: set[str]
    total_players: int
    total_rooms: int
    rank_players: int
    rank_rooms: int
    # Two-member rank rooms: matches in progress at the moment of observation.
    rank_matches: list["RoomInfoDTO"]


@dataclass
class RoomUser:
    # The fields and their order match what /rooms/all has always answered.
    online_name: str
    avatar_url: str
    npid: str


@dataclass
class RoomInfoDTO:
    room_id: int
    owner_npid: str
    owner_online_name: str
    current_members: int
    max_slots: int
    room_type: RoomType
    rank_info: Rank | None
    users: list[RoomUser]

    @classmethod
    def phantom(cls, owner_npid: str, owner_online_name: str, room_type: RoomType, rank_info: Rank | None):
        """Create a phantom room for a searching player, who has no room of their own to list."""
        return cls(
            room_id=0,
            owner_npid=owner_npid,
            owner_online_name=owner_online_name,
            current_members=1,
            max_slots=2,
            room_type=room_type,
            rank_info=rank_info,
            users=[RoomUser(online_name=owner_online_name, avatar_url="", npid=owner_npid)],
        )


# ---------------------------------------------------------------------------
# Game data (the one table every other service reads)
# ---------------------------------------------------------------------------


class CharacterOut(BaseModel):
    id: int
    name: str


class RankOut(BaseModel):
    id: int
    name: str
    tier: str


class GameDataOut(BaseModel):
    characters: list[CharacterOut]
    ranks: list[RankOut]
