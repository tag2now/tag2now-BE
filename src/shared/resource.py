"""Something opened at startup and closed at shutdown, entered on the container's exit stack."""

from abc import ABC, abstractmethod
from typing import TypeVar

_R = TypeVar("_R", bound="AsyncResource")


class AsyncResource(ABC):
    async def init(self) -> None:
        """Open what `close` releases; most resources open nothing until first use."""

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self: _R) -> _R:
        await self.init()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()
