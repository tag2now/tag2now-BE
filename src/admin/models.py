"""Moderation DTOs, and the account shape the admin port returns."""

from dataclasses import dataclass
from datetime import datetime

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
