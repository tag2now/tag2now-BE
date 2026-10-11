"""Replaceable contracts: where channels are stored, and the platform they stream on."""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from streaming.models import LiveBroadcast, PlatformChannel, StreamChannel


class StreamChannelRepository(ABC):
    @abstractmethod
    async def get(self, session: AsyncSession, username: str, platform: str) -> StreamChannel | None: ...

    @abstractmethod
    async def list_all(self, session: AsyncSession) -> list[StreamChannel]: ...

    @abstractmethod
    async def upsert(self, session: AsyncSession, username: str, platform: str,
                     channel: PlatformChannel) -> StreamChannel:
        """Set the account's channel; ChannelTakenError when another account holds it."""

    @abstractmethod
    async def delete(self, session: AsyncSession, username: str, platform: str) -> bool:
        """Remove the account's channel, matching the username regardless of case."""


class StreamPlatform(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def channel(self, channel_id: str) -> PlatformChannel | None:
        """The channel, or None when it does not exist. StreamingUnavailableError on failure."""

    @abstractmethod
    async def live(self, channel_id: str) -> LiveBroadcast | None:
        """The broadcast on air, or None when offline. StreamingUnavailableError on failure."""
