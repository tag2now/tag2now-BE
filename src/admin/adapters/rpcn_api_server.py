"""rpcn-narco API server's admin API (`admin/users/info`, `admin/users/ban`).

Both routes take the API key *and* an admin's username and password, and RPCN
checks the account is an admin that is not itself banned. This service holds no
password, so the admin re-enters theirs for every action.
"""

import logging
from datetime import datetime, timezone

import httpx

from admin.exceptions import AccountNotFoundError, AdminPasswordError, AdminUnavailableError, NotAdminError
from admin.models import AccountStatus, BanResult
from admin.ports import AccountAdmin
from shared.rpcn_password import derive_rpcn_password

logger = logging.getLogger(__name__)

_INFO_PATH = "/admin/users/info"
_BAN_PATH = "/admin/users/ban"
_UNAVAILABLE = "RPCN 관리 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."


class RpcnApiServerAccountAdmin(AccountAdmin):
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

    async def lookup(self, admin_username: str, admin_password: str, username: str) -> AccountStatus:
        body = await self._post(_INFO_PATH, admin_username, admin_password, username)
        return _read(_to_status, body)

    async def ban(self, admin_username: str, admin_password: str, username: str) -> BanResult:
        body = await self._post(_BAN_PATH, admin_username, admin_password, username)
        return _read(_to_ban_result, body)

    async def _post(self, path: str, admin_username: str, admin_password: str, username: str) -> dict:
        if self._client is None:
            raise RuntimeError("RPCN account admin not initialized")
        if not self._base_url or not self._api_key:
            logger.error("Admin API is not configured: RPCN_API_SERVER_URL or RPCN_API_SERVER_KEY is empty")
            raise AdminUnavailableError("관리 기능이 설정되지 않았습니다.")
        payload = {"admin_username": admin_username, "admin_password": derive_rpcn_password(admin_password), "username": username}
        try:
            response = await self._client.post(path, json=payload, headers={"X-API-Key": self._api_key})
        except httpx.HTTPError as exc:
            logger.warning(
                "RPCN admin API unreachable at %s%s (%s: %s); check RPCN_API_SERVER_URL",
                self._base_url, path, type(exc).__name__, exc,
            )
            raise AdminUnavailableError(_UNAVAILABLE) from exc

        _raise_for_status(response, path, admin_username)
        try:
            return response.json()
        except ValueError as exc:
            logger.error("RPCN admin API returned an unreadable body at %s: %s", path, response.text[:200])
            raise AdminUnavailableError(_UNAVAILABLE) from exc


def _raise_for_status(response: httpx.Response, path: str, admin_username: str) -> None:
    status = response.status_code
    if status == 200:
        return
    if status == 401:
        raise AdminPasswordError("비밀번호가 올바르지 않습니다.")
    if status == 403:
        # RPCN answers the same "forbidden" to a non-admin caller and to a wrong
        # API key. Login uses that key too, so a signed-in admin reaching here
        # has almost certainly lost the role; the log keeps the other reading.
        logger.warning("RPCN refused admin %s at %s (not an active admin, or a wrong API key)", admin_username, path)
        raise NotAdminError("관리자 권한이 없습니다.")
    if status == 404 and _error_code(response) == "user_not_found":
        raise AccountNotFoundError("해당 아이디의 계정이 없습니다. 대소문자까지 정확히 입력해 주세요.")
    # A bare 404 is an RPCN with the API switched off; the rest are faults on
    # either side of this call, none of them the admin's.
    logger.error("RPCN admin API answered %s at %s: %s", status, path, response.text[:200])
    raise AdminUnavailableError(_UNAVAILABLE)


def _error_code(response: httpx.Response) -> str | None:
    try:
        return response.json().get("error")
    except (ValueError, AttributeError):
        return None


def _read(convert, body: dict):
    try:
        return convert(body)
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("RPCN admin API returned an unexpected body: %s", str(body)[:200])
        raise AdminUnavailableError(_UNAVAILABLE) from exc


def _to_status(body: dict) -> AccountStatus:
    return AccountStatus(
        username=body["username"],
        online_name=body["online_name"],
        avatar_url=body.get("avatar_url", ""),
        admin=bool(body["admin"]),
        banned=bool(body["banned"]),
        online=bool(body["online"]),
        created_at=_from_epoch(body.get("creation")),
        last_login_at=_from_epoch(body.get("last_login")),
    )


def _to_ban_result(body: dict) -> BanResult:
    return BanResult(username=body["username"], kicked=bool(body["kicked"]))


def _from_epoch(seconds: int | None) -> datetime | None:
    """RPCN stores Unix seconds; an account from before the timestamp table has none."""
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)
