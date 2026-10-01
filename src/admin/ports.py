"""Replaceable contracts for RPCN account moderation and TTT2 save editing."""

from abc import ABC, abstractmethod

from admin.models import AccountStatus, BanResult


class AccountAdmin(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def lookup(self, admin_username: str, admin_password: str, username: str) -> AccountStatus:
        """Return the account, or raise AdminPasswordError / NotAdminError /
        AccountNotFoundError / AdminUnavailableError."""

    @abstractmethod
    async def ban(self, admin_username: str, admin_password: str, username: str) -> BanResult:
        """Ban the account and disconnect it if online. Same errors as lookup."""


class SaveAdmin(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def call(self, action: str, admin_username: str, admin_password: str, payload: dict) -> dict:
        """Run one save admin action (show, backups, log, set-rank, set-account-rank,
        floor, restore) as this admin and return its answer, or raise
        AdminPasswordError / NotAdminError / AccountNotFoundError / SaveNotFoundError /
        BackupNotFoundError / SaveConflictError / SaveRequestError / AdminUnavailableError."""
