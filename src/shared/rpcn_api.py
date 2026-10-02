"""rpcn-narco's API server (`RPCN_API_SERVER_URL`): one HTTP client for login
(`auth/`) and account moderation (`admin/`).

It owns what the two share --- the address, the API key, the connection pool
and its lifetime --- and reports the two failures neither caller can act on:
not configured, and no answer at all. What a status code means, and what the
user is told, stays with each caller.
"""

import logging

import httpx

from shared.settings import get_settings

logger = logging.getLogger(__name__)


class RpcnApiUnavailable(Exception):
    """No answer from the API server; the caller says so in its own words."""


class RpcnApiNotConfigured(RpcnApiUnavailable):
    """RPCN_API_SERVER_URL or RPCN_API_SERVER_KEY is empty."""


class RpcnApiUnreachable(RpcnApiUnavailable):
    """The request failed before any answer came back."""


class RpcnApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout, transport=self._transport)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def post(self, path: str, body: dict) -> httpx.Response:
        """The answer, whatever its status; RpcnApiUnavailable when there is none."""
        if self._client is None:
            raise RuntimeError("RPCN API client not initialized")
        if not self._base_url or not self._api_key:
            logger.error("RPCN API server is not configured: RPCN_API_SERVER_URL or RPCN_API_SERVER_KEY is empty")
            raise RpcnApiNotConfigured(path)
        try:
            return await self._client.post(path, json=body, headers={"X-API-Key": self._api_key})
        except httpx.HTTPError as exc:
            # The address and the kind of failure, not just the message: a bare
            # "[Errno -2] Name does not resolve" says a lookup failed without
            # saying which host, or that the host came from this setting.
            logger.warning("RPCN API server unreachable at %s%s (%s: %s); check RPCN_API_SERVER_URL",
                           self._base_url, path, type(exc).__name__, exc)
            raise RpcnApiUnreachable(path) from exc


_api: RpcnApiClient | None = None


async def init_rpcn_api() -> None:
    # Empty settings still start: login and the admin routes answer 502, and
    # init_auth says why.
    global _api
    settings = get_settings()
    _api = RpcnApiClient(settings.rpcn_api_server_url, settings.rpcn_api_server_key.get_secret_value(), settings.rpcn_api_server_timeout_seconds)
    await _api.init()


async def close_rpcn_api() -> None:
    global _api
    if _api:
        await _api.close()
        _api = None


def get_rpcn_api() -> RpcnApiClient:
    if _api is None:
        raise RuntimeError("RPCN API client not initialized")
    return _api
