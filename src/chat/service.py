"""Chat use cases: post, delete, and what a newly opened stream starts from.

Like reservation, writes name their actor by `subject` (the RPCN username) and
`display_name`; the router takes both from the signed-in user.
"""

from collections.abc import AsyncIterable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta

from chat.domain import ChatEvent, Deleted, Message, Posted, history_start
from chat.ports import ChatEventBus, ChatRepository
from shared.clock import Clock, SystemClock
from shared.exceptions import ForbiddenError, NotFoundError, RateLimitedError

# One message a second per account. Enough for a quick follow-up line, and it
# stops a held-down Enter from filling everyone's panel.
MIN_POST_INTERVAL = timedelta(seconds=1)


def ensure_not_flooding(last_post: datetime | None, now: datetime) -> None:
    if last_post is not None and now - last_post < MIN_POST_INTERVAL:
        raise RateLimitedError("메시지를 너무 빨리 보내고 있습니다. 잠시 후 다시 보내 주세요.")


class ChatService:
    def __init__(self, repo: ChatRepository, bus: ChatEventBus, clock: Clock | None = None):
        self._repo = repo
        self._bus = bus
        self._clock = clock or SystemClock()
        # Last post per subject. Memory, like the bus: a restart forgets it,
        # which at worst lets someone post twice within a second.
        self._last_post: dict[str, datetime] = {}

    def subscribe(self) -> AbstractAsyncContextManager[AsyncIterable[ChatEvent]]:
        return self._bus.subscribe()

    async def recent_messages(self) -> list[Message]:
        return await self._repo.list_since(history_start(self._clock.now()))

    async def post_message(self, *, subject: str, display_name: str, body: str, admin: bool = False) -> Message:
        now = self._clock.now()
        ensure_not_flooding(self._last_post.get(subject), now)
        message = await self._repo.append(subject, display_name, body, now, author_admin=admin)
        self._last_post[subject] = now
        await self._bus.publish(Posted(message))
        return message

    async def delete_message(self, message_id: int, *, subject: str, admin: bool) -> None:
        message = await self._repo.get(message_id)
        if message is None:
            raise NotFoundError("메시지를 찾을 수 없습니다.")
        if message.author_username != subject and not admin:
            raise ForbiddenError("본인 메시지만 삭제할 수 있습니다.")
        await self._repo.delete(message_id)
        await self._bus.publish(Deleted(message_id))
