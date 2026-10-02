"""Account moderation and save editing: this service checks who is asking,
RPCN and the save admin server decide."""

import os
from datetime import datetime, timezone

from admin.db import get_account_admin, get_save_admin
from admin.exceptions import SelfBanError
from admin.models import AccountStatus, BanResult, SaveLogRequest, SaveRequest
from auth.models import AuthUser
from saves.service import forget as forget_player_save

# Audit fields that hold a path on the RPCN host; only the file's label means
# anything here, and the path says nothing an admin needs.
_PATH_FIELDS = ("backup", "source")


async def lookup(admin: AuthUser, password: str, username: str) -> AccountStatus:
    return await get_account_admin().lookup(admin.username, password, username)


async def ban(admin: AuthUser, password: str, username: str) -> BanResult:
    ensure_not_self(admin, username)
    return await get_account_admin().ban(admin.username, password, username)


async def show_save(admin: AuthUser, request: SaveRequest) -> dict:
    save = await _save_call("show", admin, request)
    # saved_utc is a naive UTC "YYYY-MM-DD HH:MM:SS[.ffffff]"
    saved_at = datetime.fromisoformat(save["saved_utc"]).replace(tzinfo=timezone.utc)
    return {**save, "username": save["npid"], "saved_at": saved_at}


async def list_backups(admin: AuthUser, request: SaveRequest) -> dict:
    return await _save_call("backups", admin, request)


async def read_save_log(admin: AuthUser, request: SaveLogRequest) -> dict:
    answer = await _save_call("log", admin, request)
    return {"records": [_audit_record(r) for r in answer["records"]]}


async def edit_save(action: str, admin: AuthUser, request: SaveRequest) -> dict:
    """set-rank, set-account-rank, floor or restore: a preview with dry_run, else the write"""
    answer = await _save_call(action, admin, request)
    # Profiles show the save from a cache; a written one shows at once.
    if answer["applied"]:
        forget_player_save(answer["username"])
    return answer


async def _save_call(action: str, admin: AuthUser, request) -> dict:
    payload = request.model_dump(exclude={"password"}, exclude_none=True)
    return await get_save_admin().call(action, admin.username, request.password, payload)


def _audit_record(record: dict) -> dict:
    head = ("ts", "user", "action", "npid")
    details = {k: _label(v) if k in _PATH_FIELDS else v for k, v in record.items() if k not in head}
    return {"ts": record["ts"], "user": record["user"], "action": record["action"],
            "username": record["npid"], "details": details}


def _label(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def ensure_not_self(admin: AuthUser, username: str) -> None:
    # RPCN usernames are unique regardless of case, so a differently cased
    # spelling is still the admin's own account.
    if admin.username.casefold() == username.casefold():
        raise SelfBanError("자기 계정은 밴할 수 없습니다.")
