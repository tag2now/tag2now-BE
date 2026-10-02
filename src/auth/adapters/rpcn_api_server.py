"""rpcn-narco API server's external user API (`external/users/verify`).

The endpoint checks the password against RPCN's own account table and returns
the account; it creates no session on the RPCN side, so verifying never
collides with the user being logged in from RPCS3.
"""

import logging

from auth.exceptions import AuthUnavailableError, InvalidCredentialsError
from auth.models import VerifiedAccount
from auth.ports import AccountVerifier
from shared.rpcn_api import RpcnApiClient, RpcnApiNotConfigured, RpcnApiUnreachable
from shared.rpcn_password import derive_rpcn_password

logger = logging.getLogger(__name__)

_VERIFY_PATH = "/external/users/verify"


class RpcnApiServerAccountVerifier(AccountVerifier):
    def __init__(self, api: RpcnApiClient):
        self._api = api

    async def verify(self, username: str, password: str) -> VerifiedAccount:
        try:
            response = await self._api.post(_VERIFY_PATH, {"username": username, "password": derive_rpcn_password(password)})
        except RpcnApiNotConfigured as exc:
            raise AuthUnavailableError("로그인이 설정되지 않았습니다.") from exc
        except RpcnApiUnreachable as exc:
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
