from abc import ABC, abstractmethod
from collections.abc import AsyncIterable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from chat.domain import ChatEvent, Message


class ChatRepository(ABC):
    @abstractmethod
    async def append(self, author_username: str, author_online_name: str, body: str, created_at: datetime) -> Message: ...

    @abstractmethod
    async def list_since(self, boundary: datetime) -> list[Message]:
        """Messages created at or after `boundary`, oldest first."""

    @abstractmethod
    async def get(self, message_id: int) -> Message | None: ...

    @abstractmethod
    async def delete(self, message_id: int) -> None: ...


class ChatEventBus(ABC):
    """Carries chat events to every open stream.

    Async on both ends although the in-memory bus needs neither: a bus that
    spans processes (Redis pub/sub) does I/O to publish and to (un)subscribe,
    and the port has to admit it without changing shape.
    """

    @abstractmethod
    async def publish(self, event: ChatEvent) -> None: ...

    @abstractmethod
    def subscribe(self) -> AbstractAsyncContextManager[AsyncIterable[ChatEvent]]:
        """Events published from the moment this is entered, never earlier ones.

        Iteration may end on its own --- the bus can drop a reader --- and the
        caller should then end its stream so the client reconnects.
        """


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...
