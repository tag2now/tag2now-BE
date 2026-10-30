"""Chat in PostgreSQL, so a deploy or restart keeps the recent conversation."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from chat.domain import Message
from chat.entities import ChatMessageRow
from chat.ports import ChatRepository


def _message(row: ChatMessageRow) -> Message:
    return Message(
        id=row.id,
        author_username=row.author_username,
        author_online_name=row.author_online_name,
        body=row.body,
        created_at=row.created_at,
        author_admin=row.author_admin,
    )


class PostgresChatRepository(ChatRepository):
    """Rows older than the shown window are left in place: nothing reads them,
    and a chat line is small enough that purging can wait until it matters.
    Deletion removes the row."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], max_listed: int):
        self._sessions = session_factory
        self._max_listed = max_listed

    async def append(
        self,
        author_username: str,
        author_online_name: str,
        body: str,
        created_at: datetime,
        *,
        author_admin: bool = False,
    ) -> Message:
        row = ChatMessageRow(
            author_username=author_username,
            author_online_name=author_online_name,
            body=body,
            created_at=created_at,
            author_admin=author_admin,
        )
        async with self._sessions() as session, session.begin():
            session.add(row)
        return _message(row)

    async def list_since(self, boundary: datetime) -> list[Message]:
        """The newest `max_listed` of them, so a busy day cannot swell every snapshot."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ChatMessageRow)
                .where(ChatMessageRow.created_at >= boundary)
                .order_by(ChatMessageRow.id.desc())
                .limit(self._max_listed)
            )
            return [_message(row) for row in reversed(rows.all())]

    async def get(self, message_id: int) -> Message | None:
        async with self._sessions() as session:
            row = await session.get(ChatMessageRow, message_id)
            return _message(row) if row else None

    async def delete(self, message_id: int) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(delete(ChatMessageRow).where(ChatMessageRow.id == message_id))
