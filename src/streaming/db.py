"""Channel repository and streaming platform factory + lifecycle."""

from shared.settings import get_settings
from streaming.ports import StreamChannelRepository, StreamPlatform

_repo: StreamChannelRepository | None = None
_platform: StreamPlatform | None = None


async def init_streaming() -> None:
    global _repo, _platform
    from streaming.adapters.chzzk import ChzzkPlatform
    from streaming.adapters.postgresql import PostgresStreamChannelRepository

    settings = get_settings()
    _repo = PostgresStreamChannelRepository()
    _platform = ChzzkPlatform(settings.chzzk_api_url, settings.chzzk_timeout_seconds)
    await _platform.init()


async def close_streaming() -> None:
    global _repo, _platform
    if _platform:
        await _platform.close()
    _repo = None
    _platform = None


def get_channel_repo() -> StreamChannelRepository:
    if _repo is None:
        raise RuntimeError("Streaming repository not initialized — call init_streaming() first")
    return _repo


def get_stream_platform() -> StreamPlatform:
    if _platform is None:
        raise RuntimeError("Streaming platform not initialized — call init_streaming() first")
    return _platform


def set_channel_repo(repo: StreamChannelRepository | None) -> None:
    """Test seam: swap the repository without a database."""
    global _repo
    _repo = repo


def set_stream_platform(platform: StreamPlatform | None) -> None:
    """Test seam: swap the platform without going through settings."""
    global _platform
    _platform = platform
