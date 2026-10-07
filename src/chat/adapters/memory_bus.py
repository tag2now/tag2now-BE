"""The chat event bus as in-memory queues, one per open stream.

There is one process (see CLAUDE.md), so a set of queues is the whole pub/sub.
A second process would need a bus that spans them --- Redis pub/sub behind the
same `ChatEventBus` port.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from chat.domain import ChatEvent
from chat.ports import ChatEventBus

QUEUE_SIZE = 100

_CLOSED = object()


class Subscription:
    """One stream's queue. Iterating it yields events until it is dropped."""

    def __init__(self, size: int):
        self._queue: asyncio.Queue = asyncio.Queue(size)

    def offer(self, event: ChatEvent) -> bool:
        """Queue the event; False when the reader is too far behind to take it."""
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    def close(self) -> None:
        """End the iteration. What is still queued is discarded: a reader this far
        behind reconnects and gets a fresh snapshot, which supersedes it."""
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(_CLOSED)

    async def __aiter__(self) -> AsyncIterator[ChatEvent]:
        while (event := await self._queue.get()) is not _CLOSED:
            yield event


class MemoryChatEventBus(ChatEventBus):
    def __init__(self, queue_size: int = QUEUE_SIZE):
        self._queue_size = queue_size
        self._subscriptions: set[Subscription] = set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        subscription = Subscription(self._queue_size)
        self._subscriptions.add(subscription)
        try:
            yield subscription
        finally:
            self._subscriptions.discard(subscription)

    async def publish(self, event: ChatEvent) -> None:
        # A full queue means the connection has stalled --- its socket is not
        # draining. Holding events for it would grow without bound, so it is
        # dropped; EventSource reconnects on its own once the stream ends.
        for subscription in list(self._subscriptions):
            if not subscription.offer(event):
                self._subscriptions.discard(subscription)
                subscription.close()
