"""Idempotency keys in PostgreSQL, where the unique index decides who runs."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from idempotency.entities import IdempotencyKeyRow
from idempotency.exceptions import IdempotencyKeyReusedError
from idempotency.ports import IdempotencyStore


class PostgresIdempotencyStore(IdempotencyStore):
    async def claim(self, session, subject, key, fingerprint):
        # A concurrent duplicate blocks here on the first one's uncommitted index
        # entry, then conflicts once it commits --- or inserts if it rolled back.
        claimed = await session.scalar(
            insert(IdempotencyKeyRow)
            .values(subject=subject, key=key, fingerprint=fingerprint)
            .on_conflict_do_nothing(index_elements=["subject", "key"])
            .returning(IdempotencyKeyRow.id)
        )
        if claimed is not None:
            return None
        # READ COMMITTED: this statement sees the row the conflict was with.
        stored = (
            await session.execute(
                select(IdempotencyKeyRow.fingerprint, IdempotencyKeyRow.response).where(
                    IdempotencyKeyRow.subject == subject, IdempotencyKeyRow.key == key
                )
            )
        ).one()
        if stored.fingerprint != fingerprint:
            raise IdempotencyKeyReusedError("이미 다른 요청에 쓰인 요청 키입니다. 새로고침 후 다시 시도해 주세요.")
        return stored.response

    async def complete(self, session, subject, key, response):
        await session.execute(
            update(IdempotencyKeyRow)
            .where(IdempotencyKeyRow.subject == subject, IdempotencyKeyRow.key == key)
            .values(response=response)
        )
