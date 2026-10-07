"""Chat use cases: post, delete, and what a newly opened stream starts from.

Like reservation, writes name their actor by `subject` (the RPCN username) and
`display_name`; the router takes both from the signed-in user. The service
knows only the ports --- the repository, event bus and clock are injected by
`chat.db`, which is the seam the tests use as well.
"""

from collections.abc import AsyncIterable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

from chat.domain import ChatEvent, Deleted, Message, Posted, day_start
from chat.ports import ChatEventBus, ChatRepository, Clock
from shared.exceptions import ForbiddenError, NotFoundError, RateLimitedError

# One message a second per account. Enough for a quick follow-up line, and it
# stops a held-down Enter from filling everyone's panel.
MIN_POST_INTERVAL = timedelta(seconds=1)


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


_repo: ChatRepository | None = None
_bus: ChatEventBus | None = None
_clock: Clock = SystemClock()
# Last post per subject. Memory, like everything else here: a restart forgets
# it, which at worst lets someone post twice within a second.
_last_post: dict[str, datetime] = {}


def configure(repository: ChatRepository, bus: ChatEventBus, clock: Clock | None = None) -> None:
    global _repo, _bus, _clock
    _repo = repository
    _bus = bus
    _clock = clock or SystemClock()
    _last_post.clear()


def _repository() -> ChatRepository:
    if _repo is None:
        raise RuntimeError("Chat repository not initialized")
    return _repo


def _event_bus() -> ChatEventBus:
    if _bus is None:
        raise RuntimeError("Chat event bus not initialized")
    return _bus


def ensure_not_flooding(last_post: datetime | None, now: datetime) -> None:
    if last_post is not None and now - last_post < MIN_POST_INTERVAL:
        raise RateLimitedError("메시지를 너무 빨리 보내고 있습니다. 잠시 후 다시 보내 주세요.")


def subscribe() -> AbstractAsyncContextManager[AsyncIterable[ChatEvent]]:
    return _event_bus().subscribe()


async def todays_messages() -> list[Message]:
    return await _repository().list_since(day_start(_clock.now()))


async def post_message(*, subject: str, display_name: str, body: str) -> Message:
    now = _clock.now()
    ensure_not_flooding(_last_post.get(subject), now)
    message = await _repository().append(subject, display_name, body, now)
    _last_post[subject] = now
    await _event_bus().publish(Posted(message))
    return message


async def delete_message(message_id: int, *, subject: str, admin: bool) -> None:
    message = await _repository().get(message_id)
    if message is None:
        raise NotFoundError("메시지를 찾을 수 없습니다.")
    if message.author_username != subject and not admin:
        raise ForbiddenError("본인 메시지만 삭제할 수 있습니다.")
    await _repository().delete(message_id)
    await _event_bus().publish(Deleted(message_id))
