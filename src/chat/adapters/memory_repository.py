from collections import deque
from datetime import datetime

from chat.domain import Message
from chat.ports import ChatRepository


class MemoryChatRepository(ChatRepository):
    """Today's chat in process memory.

    It lives and dies with the process, so a backend deploy empties it --- an
    accepted cost for a channel that only ever shows one day. There is one
    process (see CLAUDE.md), so one deque is the whole store.

    The deque is bounded rather than purged at 06:00: `list_since` already
    hides the previous day, and the bound is what keeps a busy day from
    growing without limit. Ids restart from 1 with the process; a client
    replaces its list with the snapshot every stream opens with, so a reused
    id never meets the old one.
    """

    def __init__(self, max_kept: int):
        self._messages: deque[Message] = deque(maxlen=max_kept)
        self._next_id = 1

    async def append(self, author_username: str, author_online_name: str, body: str, created_at: datetime) -> Message:
        message = Message(self._next_id, author_username, author_online_name, body, created_at)
        self._next_id += 1
        self._messages.append(message)
        return message

    async def list_since(self, boundary: datetime) -> list[Message]:
        return [m for m in self._messages if m.created_at >= boundary]

    async def get(self, message_id: int) -> Message | None:
        return next((m for m in self._messages if m.id == message_id), None)

    async def delete(self, message_id: int) -> None:
        self._messages = deque((m for m in self._messages if m.id != message_id), maxlen=self._messages.maxlen)
