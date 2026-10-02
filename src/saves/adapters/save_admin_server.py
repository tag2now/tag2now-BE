"""tag2now-save-admin's server, `GET /player/save`: the one route it serves
without an admin, so it needs only the API key."""

import logging

import httpx

from saves.exceptions import SavesUnavailableError
from saves.ports import PlayerSaves

logger = logging.getLogger(__name__)

_UNAVAILABLE = "세이브 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."

# Both mean "nothing to show" to a profile, which is not a fault to log.
_NOT_FOUND = {"user_not_found", "save_not_found"}


class SaveAdminServerPlayerSaves(PlayerSaves):
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

    async def read(self, npid: str) -> dict | None:
        if self._client is None:
            raise RuntimeError("Player saves not initialized")
        if not self._base_url or not self._api_key:
            logger.error("Player saves are not configured: SAVE_ADMIN_URL or SAVE_ADMIN_KEY is empty")
            raise SavesUnavailableError(_UNAVAILABLE)
        try:
            response = await self._client.get("/player/save", params={"username": npid},
                                              headers={"X-API-Key": self._api_key})
        except httpx.HTTPError as exc:
            logger.warning("Save server unreachable at %s (%s: %s); check SAVE_ADMIN_URL",
                           self._base_url, type(exc).__name__, exc)
            raise SavesUnavailableError(_UNAVAILABLE) from exc

        answer = _json(response)
        if response.status_code == 200 and answer is not None:
            return answer
        if (answer or {}).get("error") in _NOT_FOUND:
            return None
        logger.error("Save server answered %s for %s: %s", response.status_code, npid, response.text[:200])
        raise SavesUnavailableError(_UNAVAILABLE)


def _json(response: httpx.Response) -> dict | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None
