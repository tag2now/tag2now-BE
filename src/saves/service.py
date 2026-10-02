"""TTT2 saves: anyone's ranks for a profile, and an admin's reads and edits.

The profile read goes through a cache. The game rewrites the save when a
session ends, and a rank seen a few minutes late costs nothing, so an answer is
kept for cache_ttl_player_save --- a missing save too, or a profile with no save
would ask the server every time. An admin's written edit drops the entry at once.

Admin calls go straight to the server, which checks the admin's password with
RPCN every time.
"""

import os
from datetime import datetime, timezone

from auth.models import AuthUser
from saves.db import get_save_server
from saves.exceptions import SaveNotFoundError
from saves.models import SaveLogRequest, SaveRequest
from shared.cache import cache_delete_pattern, cache_get, cache_set
from shared.settings import get_settings

# Audit fields that hold a path on the RPCN host; only the file's label means
# anything here, and the path says nothing an admin needs.
_PATH_FIELDS = ("backup", "source")


# --- profile --------------------------------------------------------------------

def _key(npid: str) -> str:
    # RPCN usernames are unique regardless of case, and an admin may type any case.
    return f"saves:player:{npid.casefold()}"


async def get_player_save(npid: str) -> dict:
    key = _key(npid)
    if (entry := cache_get(key)) is None:
        entry = {"save": _profile(await get_save_server().read(npid))}
        cache_set(key, entry, get_settings().cache_ttl_player_save)
    if entry["save"] is None:
        raise SaveNotFoundError("이 플레이어의 TTT2 세이브가 없습니다.")
    return entry["save"]


def _profile(save: dict | None) -> dict | None:
    if save is None:
        return None
    return {"username": save["npid"], "saved_at": _saved_at(save), "account_rank": save["account_rank"],
            "total": save["total"], "wins": save["wins"], "losses": save["losses"], "chars": save["chars"]}


# --- admin ----------------------------------------------------------------------

async def show_save(admin: AuthUser, request: SaveRequest) -> dict:
    save = await _admin_call("show", admin, request)
    return {**save, "username": save["npid"], "saved_at": _saved_at(save)}


async def list_backups(admin: AuthUser, request: SaveRequest) -> dict:
    return await _admin_call("backups", admin, request)


async def read_save_log(admin: AuthUser, request: SaveLogRequest) -> dict:
    answer = await _admin_call("log", admin, request)
    return {"records": [_audit_record(r) for r in answer["records"]]}


async def edit_save(action: str, admin: AuthUser, request: SaveRequest) -> dict:
    """set-rank, set-account-rank, floor or restore: a preview with dry_run, else the write"""
    answer = await _admin_call(action, admin, request)
    # Profiles show the save from a cache; a written one shows at once.
    if answer["applied"]:
        cache_delete_pattern(_key(answer["username"]))
    return answer


async def _admin_call(action: str, admin: AuthUser, request) -> dict:
    payload = request.model_dump(exclude={"password"}, exclude_none=True)
    return await get_save_server().call(action, admin.username, request.password, payload)


def _audit_record(record: dict) -> dict:
    head = ("ts", "user", "action", "npid")
    details = {k: _label(v) if k in _PATH_FIELDS else v for k, v in record.items() if k not in head}
    return {"ts": record["ts"], "user": record["user"], "action": record["action"],
            "username": record["npid"], "details": details}


def _label(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _saved_at(save: dict) -> datetime:
    # saved_utc is a naive UTC "YYYY-MM-DD HH:MM:SS[.ffffff]"
    return datetime.fromisoformat(save["saved_utc"]).replace(tzinfo=timezone.utc)
