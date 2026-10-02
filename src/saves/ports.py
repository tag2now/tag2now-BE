"""Replaceable contract for the server that holds TTT2 saves."""

from abc import ABC, abstractmethod


class SaveServer(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def read(self, npid: str) -> dict | None:
        """The save's ranks and records as anyone may see them, or None when
        there is no such account or it has never saved TTT2.
        SavesUnavailableError when the server cannot answer."""

    @abstractmethod
    async def call(self, action: str, admin_username: str, admin_password: str, payload: dict) -> dict:
        """Run one admin action (show, backups, log, set-rank, set-account-rank,
        floor, restore) as this admin and return its answer, or raise
        AdminPasswordError / NotAdminError / AccountNotFoundError / SaveNotFoundError /
        BackupNotFoundError / SaveConflictError / SaveRequestError / SavesUnavailableError."""
