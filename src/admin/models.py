"""Moderation and save admin DTOs, and the account shape the admin port returns."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class AccountStatus:
    username: str
    online_name: str
    avatar_url: str
    admin: bool
    banned: bool
    online: bool
    created_at: datetime | None
    last_login_at: datetime | None


@dataclass(frozen=True)
class BanResult:
    username: str
    # Whether the account was in-game and got disconnected, not just flagged.
    kicked: bool


class AdminActionRequest(BaseModel):
    # The target account. rpcn-narco matches it exactly, case included.
    username: str = Field(..., min_length=1, max_length=64)
    # The admin's own password, re-entered: RPCN checks it on every action.
    password: str = Field(..., min_length=1, max_length=128)


class AccountStatusOut(BaseModel):
    username: str
    online_name: str
    avatar_url: str
    admin: bool
    banned: bool
    online: bool
    created_at: datetime | None
    last_login_at: datetime | None


class BanOut(BaseModel):
    username: str
    banned: bool = True
    kicked: bool


# --- TTT2 saves ---------------------------------------------------------------
# Rank codes run 0 (Beginner) to 42 (True Tekken God); characters 0 to 58.
RankCode = Annotated[int, Field(ge=0, le=42)]
# Floor ranks need floor points, which start at 1 (9th kyu).
FloorRank = Annotated[int, Field(ge=1, le=42)]


class SaveRequest(BaseModel):
    # The target account; matched regardless of case.
    username: str = Field(..., min_length=1, max_length=64)
    # The admin's own password, re-entered: RPCN checks it on every action.
    password: str = Field(..., min_length=1, max_length=128)


class ShowSaveRequest(SaveRequest):
    # Every character slot, not only those with a rank or a match played.
    all_chars: bool = False


class SaveLogRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    # One account's records; every account's when left out.
    username: str | None = Field(None, min_length=1, max_length=64)
    n: int = Field(50, ge=1, le=500)


class SaveWriteRequest(SaveRequest):
    # Answer what would change, with the save's sha256, and write nothing.
    dry_run: bool = False
    # The sha256 the preview answered; required to write, so an edit never
    # lands on a save that changed after the admin looked at it.
    expect_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")


class SetRankRequest(SaveWriteRequest):
    # A character slot, or "all" for every character and the account rank.
    char: Annotated[int, Field(ge=0, le=58)] | Literal["all"]
    rank: RankCode
    # Rank points; kept as they are when left out. Not with "all".
    points: int | None = Field(None, ge=0, le=65535)


class SetAccountRankRequest(SaveWriteRequest):
    rank: RankCode


class FloorRequest(SaveWriteRequest):
    # The floor; two tiers below the highest rank reached when left out.
    rank: FloorRank | None = None
    # Also top up the points of characters already at the floor.
    fix_points: bool = False
    # Raise a few characters below the floor anyway, which normally read as
    # demotions after an earlier floor and are left alone.
    refloor: bool = False


class RestoreRequest(SaveWriteRequest):
    label: str = Field(..., max_length=64, pattern=r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")


class SaveCharOut(BaseModel):
    id: int
    character: str
    rank: int
    rank_name: str
    tier: str
    points: int
    streak: int
    wins: int
    losses: int


class SaveOut(BaseModel):
    username: str
    data_id: int
    # When the game last wrote this save.
    saved_at: datetime
    sha256: str
    checksum_ok: bool
    account_rank: int
    # The account rank's progress gauge, out of 11.
    progress: int
    total: int
    wins: int
    losses: int
    # Whether the player is in-game now; null when RPCN cannot say.
    online: bool | None
    chars: list[SaveCharOut]


class BackupOut(BaseModel):
    label: str
    # null for a backup file of the wrong size.
    total: int | None
    account_rank: int | None


class BackupsOut(BaseModel):
    backups: list[BackupOut]


class AuditRecordOut(BaseModel):
    ts: str
    # Who did it: the admin for site edits, the shell user otherwise.
    user: str
    action: str
    # The account, or "-" for a batch.
    username: str
    details: dict[str, Any]


class SaveLogOut(BaseModel):
    records: list[AuditRecordOut]


class SlotStateOut(BaseModel):
    rank: int
    rank_name: str
    points: int
    streak: int


class CharChangeOut(BaseModel):
    id: int
    character: str
    before: SlotStateOut
    after: SlotStateOut


class AccountRankChangeOut(BaseModel):
    before: int
    after: int


class SaveChangesOut(BaseModel):
    account_rank: AccountRankChangeOut | None
    chars: list[CharChangeOut]


class WriteResultOut(BaseModel):
    # The backup taken just before the write; restore takes this label.
    backup: str
    checksum: str
    data_id: int
    # False when the game saved over it while it was written: the edit is lost.
    landed: bool


class SaveWriteOut(BaseModel):
    username: str
    # The save before the change: send it back as expect_sha256 to write.
    sha256: str
    online: bool | None
    changes: SaveChangesOut
    applied: bool
    result: WriteResultOut | None


class FloorOut(BaseModel):
    reached: int
    floor: int
    raised: int
    points_fixed: int
    # A few characters below the floor, which an earlier floor would explain as
    # demotions since; writing then needs refloor.
    likely_demoted: bool


class FloorWriteOut(SaveWriteOut):
    floor: FloorOut
