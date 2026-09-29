"""Account moderation: this service checks who is asking, RPCN decides."""

from admin.db import get_account_admin
from admin.exceptions import SelfBanError
from admin.models import AccountStatus, BanResult
from auth.models import AuthUser


async def lookup(admin: AuthUser, password: str, username: str) -> AccountStatus:
    return await get_account_admin().lookup(admin.username, password, username)


async def ban(admin: AuthUser, password: str, username: str) -> BanResult:
    ensure_not_self(admin, username)
    return await get_account_admin().ban(admin.username, password, username)


def ensure_not_self(admin: AuthUser, username: str) -> None:
    # RPCN usernames are unique regardless of case, so a differently cased
    # spelling is still the admin's own account.
    if admin.username.casefold() == username.casefold():
        raise SelfBanError("자기 계정은 밴할 수 없습니다.")
