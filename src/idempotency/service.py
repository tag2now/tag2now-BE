"""Run a write at most once per idempotency key.

Called inside the caller's transaction, so the key, the write and the stored
answer commit together or not at all: a failed write leaves no key behind, and
its retry runs again.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from idempotency.domain import fingerprint
from idempotency.ports import IdempotencyStore


class IdempotencyService:
    def __init__(self, store: IdempotencyStore):
        self._store = store

    async def run_once(
        self,
        session: AsyncSession,
        subject: str,
        key: str,
        scope: str,
        request: dict,
        write: Callable[[], Awaitable[Any]],
    ) -> Any:
        """The write's answer as JSON --- the first time, and every retry after."""
        stored = await self._store.claim(session, subject, key, fingerprint(scope, request))
        if stored is not None:
            return stored
        answer = to_jsonable_python(await write())
        await self._store.complete(session, subject, key, answer)
        return answer
