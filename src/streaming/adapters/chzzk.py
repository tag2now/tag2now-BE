"""Chzzk through its web API (api.chzzk.naver.com).

The official Open API lists live broadcasts but cannot look one channel up, so
this uses the endpoints chzzk.naver.com itself calls. They are unofficial and
may change without notice.
"""

import logging

import httpx

from streaming.exceptions import StreamingUnavailableError
from streaming.models import LiveBroadcast, PlatformChannel
from streaming.ports import StreamPlatform

logger = logging.getLogger(__name__)

_UNAVAILABLE = "치지직에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."

# /service/v1/channels never answers httpx's default User-Agent; a browser's gets through.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
}


class ChzzkPlatform(StreamPlatform):
    def __init__(self, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout,
                                         headers=_HEADERS, transport=self._transport)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def channel(self, channel_id: str) -> PlatformChannel | None:
        content = await self._content(f"/service/v1/channels/{channel_id}")
        # An unknown id answers 200 with a null channelId, not 404.
        if not content or not content.get("channelId"):
            return None
        return PlatformChannel(channel_id=content["channelId"], channel_name=content.get("channelName") or "")

    async def live(self, channel_id: str) -> LiveBroadcast | None:
        content = await self._content(f"/polling/v2/channels/{channel_id}/live-status")
        if not content or content.get("status") != "OPEN":
            return None
        return LiveBroadcast(
            title=content.get("liveTitle") or "",
            viewer_count=int(content.get("concurrentUserCount") or 0),
            category=content.get("liveCategoryValue") or "",
        )

    async def _content(self, path: str) -> dict | None:
        """The answer's `content`, or None for a 404."""
        if self._client is None:
            raise RuntimeError("Chzzk client not initialized")
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            logger.warning("Chzzk unreachable at %s (%s: %s)", path, type(exc).__name__, exc)
            raise StreamingUnavailableError(_UNAVAILABLE) from exc
        if response.status_code == 404:
            return None
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            logger.error("Chzzk answered %s at %s: %s", response.status_code, path, response.text[:200])
            raise StreamingUnavailableError(_UNAVAILABLE)
        content = body.get("content")
        return content if isinstance(content, dict) else None
