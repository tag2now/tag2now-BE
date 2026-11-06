"""Replaceable contract: where idempotency keys and their answers are kept."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession


class IdempotencyStore(ABC):
    @abstractmethod
    async def claim(self, session: AsyncSession, subject: str, key: str, fingerprint: str) -> dict | None:
        """Take the key for this transaction, or return the answer it already has.

        None means the caller owns the key and must run the write. A key already
        used for a different request raises IdempotencyKeyReusedError.
        """

    @abstractmethod
    async def complete(self, session: AsyncSession, subject: str, key: str, response: dict) -> None:
        """Keep the answer, in the same transaction that claimed the key."""
