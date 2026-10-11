"""Streaming channels registered by their owners, and which of them are live.

Only the players the caller asks about are checked, so calls to the platform
grow with who is in a room, not with how many have registered.
"""

import asyncio
from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from auth.models import AuthUser
from shared.cache import cache_delete_pattern, cache_get, cache_set
from shared.database import read_only, transactional
from shared.settings import get_settings
from streaming.db import get_channel_repo, get_stream_platform
from streaming.domain import CHZZK, chzzk_live_url, parse_chzzk_channel_id
from streaming.exceptions import ChannelNotFoundError, InvalidChannelError, StreamingUnavailableError
from streaming.models import PlatformChannel, StreamChannel

CHANNELS_KEY = "streaming:channels"
_CONCURRENCY = 8
_LIVE_URL = {CHZZK: chzzk_live_url}


def _live_key(channel_id: str) -> str:
    return f"streaming:live:{channel_id}"


def _channel_out(channel: StreamChannel) -> dict:
    return {"platform": channel.platform, "channel_id": channel.channel_id, "channel_name": channel.channel_name,
            "channel_url": _LIVE_URL[channel.platform](channel.channel_id), "registered_at": channel.registered_at}


# --- live ---------------------------------------------------------------------

async def live_for(npids: Collection[str]) -> dict[str, dict]:
    """The broadcast each of these players is on air with, keyed by lower-cased username."""
    if not npids:
        return {}
    registered = await _registered_channels()
    wanted = {npid.lower() for npid in npids} & registered.keys()
    limit = asyncio.Semaphore(_CONCURRENCY)

    async def check(username: str) -> tuple[str, dict | None]:
        async with limit:
            return username, await _live(registered[username]["channel_id"])

    results = await asyncio.gather(*(check(username) for username in wanted))
    return {username: {**_stream_head(registered[username]), **broadcast}
            for username, broadcast in results if broadcast}


def _stream_head(channel: dict) -> dict:
    return {"platform": channel["platform"], "channel_name": channel["channel_name"],
            "url": _LIVE_URL[channel["platform"]](channel["channel_id"])}


async def _registered_channels() -> dict[str, dict]:
    if (cached := cache_get(CHANNELS_KEY)) is not None:
        return cached
    channels = {c.username.lower(): {"platform": c.platform, "channel_id": c.channel_id, "channel_name": c.channel_name}
                for c in await _list_all()}
    cache_set(CHANNELS_KEY, channels, get_settings().cache_ttl_stream_channels)
    return channels


async def _live(channel_id: str) -> dict | None:
    # Offline is cached as {}, since None reads as a miss.
    if (cached := cache_get(_live_key(channel_id))) is not None:
        return cached or None
    try:
        broadcast = await get_stream_platform().live(channel_id)
    except StreamingUnavailableError:
        # One failing channel must not hide the others; cached as offline so it is retried after the TTL, not per request.
        broadcast = None
    found = {"title": broadcast.title, "viewer_count": broadcast.viewer_count} if broadcast else {}
    cache_set(_live_key(channel_id), found, get_settings().cache_ttl_live_streams)
    return found or None


# --- own channel --------------------------------------------------------------

async def get_my_channel(user: AuthUser) -> dict:
    channel = await _get(user.username)
    return {"channel": _channel_out(channel) if channel else None}


async def register_channel(user: AuthUser, text: str) -> dict:
    channel_id = parse_chzzk_channel_id(text)
    if channel_id is None:
        raise InvalidChannelError("치지직 채널 주소를 확인해 주세요. 예: https://chzzk.naver.com/채널ID")
    found = await get_stream_platform().channel(channel_id)
    if found is None:
        raise InvalidChannelError("치지직에서 찾을 수 없는 채널입니다.")
    channel = await _upsert(user.username, found)
    cache_delete_pattern(CHANNELS_KEY)
    return {"channel": _channel_out(channel)}


async def unregister_channel(user: AuthUser) -> None:
    await _delete(user.username)
    cache_delete_pattern(CHANNELS_KEY)


# --- admin --------------------------------------------------------------------

async def list_channels() -> dict:
    channels = await _list_all()
    return {"channels": [{**_channel_out(c), "username": c.username} for c in channels]}


async def remove_channel(username: str) -> None:
    if not await _delete(username):
        raise ChannelNotFoundError("연결된 방송 채널이 없습니다.")
    cache_delete_pattern(CHANNELS_KEY)


# --- persistence --------------------------------------------------------------

@read_only
async def _get(session: AsyncSession, username: str) -> StreamChannel | None:
    return await get_channel_repo().get(session, username, CHZZK)


@read_only
async def _list_all(session: AsyncSession) -> list[StreamChannel]:
    return await get_channel_repo().list_all(session)


@transactional
async def _upsert(session: AsyncSession, username: str, channel: PlatformChannel) -> StreamChannel:
    return await get_channel_repo().upsert(session, username, CHZZK, channel)


@transactional
async def _delete(session: AsyncSession, username: str) -> bool:
    return await get_channel_repo().delete(session, username, CHZZK)
