"""Replaceable contract for reading a player's TTT2 save."""

from abc import ABC, abstractmethod


class PlayerSaves(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def read(self, npid: str) -> dict | None:
        """The save's ranks and records, or None when there is no such account
        or it has never saved TTT2. SavesUnavailableError when the save server
        cannot answer."""
