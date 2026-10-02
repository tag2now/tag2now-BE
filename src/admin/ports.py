"""Replaceable contract for RPCN account moderation."""

from abc import ABC, abstractmethod

from admin.models import AccountStatus, BanResult


class AccountAdmin(ABC):
    @abstractmethod
    async def lookup(self, admin_username: str, admin_password: str, username: str) -> AccountStatus:
        """Return the account, or raise AdminPasswordError / NotAdminError /
        AccountNotFoundError / AdminUnavailableError."""

    @abstractmethod
    async def ban(self, admin_username: str, admin_password: str, username: str) -> BanResult:
        """Ban the account and disconnect it if online. Same errors as lookup."""
