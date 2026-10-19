from collections import deque
from datetime import datetime

from chat.domain import Message
from chat.ports import ChatRepository


class MemoryChatRepository(ChatRepository):
    """Recent chat in process memory, for tests; production keeps chat in
    PostgreSQL (`adapters/postgresql.py`).

    The deque is bounded rather than purged at 06:00: `list_since` already
    hides anything older. Ids restart from 1 with each instance.
    """

    def __init__(self, max_kept: int):
        self._messages: deque[Message] = deque(maxlen=max_kept)
        self._next_id = 1

    async def append(
        self, author_username: str, author_online_name: str, body: str, created_at: datetime, *, author_admin: bool = False
    ) -> Message:
        message = Message(self._next_id, author_username, author_online_name, body, created_at, author_admin)
        self._next_id += 1
        self._messages.append(message)
        return message

    async def list_since(self, boundary: datetime) -> list[Message]:
        return [m for m in self._messages if m.created_at >= boundary]

    async def get(self, message_id: int) -> Message | None:
        return next((m for m in self._messages if m.id == message_id), None)

    async def delete(self, message_id: int) -> None:
        self._messages = deque((m for m in self._messages if m.id != message_id), maxlen=self._messages.maxlen)
