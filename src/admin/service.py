"""Account moderation: this service checks who is asking, RPCN decides."""

from admin.exceptions import SelfBanError
from admin.models import AccountStatus, BanResult
from admin.ports import AccountAdmin
from auth.models import AuthUser


def ensure_not_self(admin: AuthUser, username: str) -> None:
    # RPCN usernames are unique regardless of case, so a differently cased
    # spelling is still the admin's own account.
    if admin.username.casefold() == username.casefold():
        raise SelfBanError("자기 계정은 밴할 수 없습니다.")


class AdminService:
    def __init__(self, account_admin: AccountAdmin):
        self._account_admin = account_admin

    async def lookup(self, admin: AuthUser, password: str, username: str) -> AccountStatus:
        return await self._account_admin.lookup(admin.username, password, username)

    async def ban(self, admin: AuthUser, password: str, username: str) -> BanResult:
        ensure_not_self(admin, username)
        return await self._account_admin.ban(admin.username, password, username)
