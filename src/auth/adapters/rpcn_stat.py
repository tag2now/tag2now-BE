"""RPCN stat server's external user API (rpcn-narco `external/users/verify`).

The endpoint checks the password against RPCN's own account table and returns
the account; it creates no session on the RPCN side, so verifying never
collides with the user being logged in from RPCS3.
"""

import logging

import httpx

from auth.exceptions import AuthUnavailableError, InvalidCredentialsError
from auth.models import VerifiedAccount
from auth.ports import AccountVerifier

logger = logging.getLogger(__name__)

_VERIFY_PATH = "/external/users/verify"


class RpcnStatAccountVerifier(AccountVerifier):
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

    async def verify(self, username: str, password: str) -> VerifiedAccount:
        if self._client is None:
            raise RuntimeError("RPCN account verifier not initialized")
        if not self._base_url or not self._api_key:
            raise AuthUnavailableError("로그인이 설정되지 않았습니다.")
        try:
            response = await self._client.post(
                _VERIFY_PATH,
                json={"username": username, "password": password},
                headers={"X-API-Key": self._api_key},
            )
        except httpx.HTTPError as exc:
            logger.warning("RPCN account verification unreachable: %s", exc)
            raise AuthUnavailableError("로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from exc

        if response.status_code == 401:
            raise InvalidCredentialsError("아이디 또는 비밀번호가 올바르지 않습니다.")
        if response.status_code != 200:
            # 403 is a wrong API key and 404 an RPCN with the API switched off:
            # both are this deployment's fault, never the user's.
            logger.error("RPCN account verification answered %s: %s", response.status_code, response.text[:200])
            raise AuthUnavailableError("로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")

        try:
            body = response.json()
            return VerifiedAccount(
                username=body["username"],
                online_name=body["online_name"],
                avatar_url=body.get("avatar_url", ""),
                admin=bool(body.get("admin", False)),
                banned=bool(body.get("banned", False)),
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.error("RPCN account verification returned an unreadable body: %s", response.text[:200])
            raise AuthUnavailableError("로그인 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from exc
