"""Streaming channels registered by their owners, and which of them are live.

Only the players the caller asks about are checked, so calls to the platform
grow with who is in a room, not with how many have registered.
"""

import asyncio
import logging
from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth.models import AuthUser
from shared.cache import cache_delete, cache_get, cache_set
from shared.settings import get_settings
from streaming.domain import CHZZK, chzzk_live_url, parse_chzzk_channel_id
from streaming.exceptions import ChannelNotFoundError, InvalidChannelError, StreamingUnavailableError
from streaming.models import PlatformChannel, StreamChannel
from streaming.ports import StreamChannelRepository, StreamPlatform

logger = logging.getLogger(__name__)

CHANNELS_KEY = "streaming:channels"
_CONCURRENCY = 8
_LIVE_URL = {CHZZK: chzzk_live_url}


def _live_key(channel_id: str) -> str:
    return f"streaming:live:{channel_id}"


def _channel_out(channel: StreamChannel) -> dict:
    return {
        "platform": channel.platform,
        "channel_id": channel.channel_id,
        "channel_name": channel.channel_name,
        "channel_url": _LIVE_URL[channel.platform](channel.channel_id),
        "registered_at": channel.registered_at,
    }


def _stream_head(channel: dict) -> dict:
    return {
        "platform": channel["platform"],
        "channel_name": channel["channel_name"],
        "url": _LIVE_URL[channel["platform"]](channel["channel_id"]),
    }


class StreamingService:
    def __init__(
        self, repo: StreamChannelRepository, platform: StreamPlatform, sessions: async_sessionmaker[AsyncSession]
    ):
        self._repo = repo
        self._platform = platform
        self._sessions = sessions

    # -- live ----------------------------------------------------------------

    async def live_for(self, npids: Collection[str]) -> dict[str, dict]:
        """The broadcast each of these players is on air with, keyed by lower-cased username."""
        if not npids:
            return {}
        registered = await self._registered_channels()
        wanted = {npid.lower() for npid in npids} & registered.keys()
        limit = asyncio.Semaphore(_CONCURRENCY)

        async def check(username: str) -> tuple[str, dict | None]:
            async with limit:
                return username, await self._live(registered[username]["channel_id"])

        results = await asyncio.gather(*(check(username) for username in wanted))
        return {
            username: {**_stream_head(registered[username]), **broadcast}
            for username, broadcast in results
            if broadcast
        }

    async def live_or_empty(self, npids: Collection[str]) -> dict[str, dict]:
        """live_for, or nobody when it fails: callers show streams as an extra."""
        try:
            return await self.live_for(npids)
        except Exception:
            logger.warning("Live streams unavailable; answering without them", exc_info=True)
            return {}

    async def _registered_channels(self) -> dict[str, dict]:
        if (cached := cache_get(CHANNELS_KEY)) is not None:
            return cached
        channels = {
            c.username.lower(): {"platform": c.platform, "channel_id": c.channel_id, "channel_name": c.channel_name}
            for c in await self._list_all()
        }
        cache_set(CHANNELS_KEY, channels, get_settings().cache_ttl_stream_channels)
        return channels

    async def _live(self, channel_id: str) -> dict | None:
        # Offline is cached as {}, since None reads as a miss.
        if (cached := cache_get(_live_key(channel_id))) is not None:
            return cached or None
        try:
            broadcast = await self._platform.live(channel_id)
        except StreamingUnavailableError:
            # One failing channel must not hide the others; cached as offline so it is retried after the TTL, not per request.
            broadcast = None
        found = {"title": broadcast.title, "viewer_count": broadcast.viewer_count} if broadcast else {}
        cache_set(_live_key(channel_id), found, get_settings().cache_ttl_live_streams)
        return found or None

    # -- own channel ---------------------------------------------------------

    async def get_my_channel(self, user: AuthUser) -> dict:
        channel = await self._get(user.username)
        return {"channel": _channel_out(channel) if channel else None}

    async def register_channel(self, user: AuthUser, text: str) -> dict:
        channel_id = parse_chzzk_channel_id(text)
        if channel_id is None:
            raise InvalidChannelError("치지직 채널 주소를 확인해 주세요. 예: https://chzzk.naver.com/채널ID")
        found = await self._platform.channel(channel_id)
        if found is None:
            raise InvalidChannelError("치지직에서 찾을 수 없는 채널입니다.")
        channel = await self._upsert(user.username, found)
        cache_delete(CHANNELS_KEY)
        return {"channel": _channel_out(channel)}

    async def unregister_channel(self, user: AuthUser) -> None:
        await self._delete(user.username)
        cache_delete(CHANNELS_KEY)

    # -- admin ---------------------------------------------------------------

    async def list_channels(self) -> dict:
        channels = await self._list_all()
        return {"channels": [{**_channel_out(c), "username": c.username} for c in channels]}

    async def remove_channel(self, username: str) -> None:
        if not await self._delete(username):
            raise ChannelNotFoundError("연결된 방송 채널이 없습니다.")
        cache_delete(CHANNELS_KEY)

    # -- persistence: reads take a plain session, writes a transaction --------

    async def _get(self, username: str) -> StreamChannel | None:
        async with self._sessions() as session:
            return await self._repo.get(session, username, CHZZK)

    async def _list_all(self) -> list[StreamChannel]:
        async with self._sessions() as session:
            return await self._repo.list_all(session)

    async def _upsert(self, username: str, channel: PlatformChannel) -> StreamChannel:
        async with self._sessions() as session, session.begin():
            return await self._repo.upsert(session, username, CHZZK, channel)

    async def _delete(self, username: str) -> bool:
        async with self._sessions() as session, session.begin():
            return await self._repo.delete(session, username, CHZZK)
