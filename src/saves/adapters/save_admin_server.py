"""tag2now-save-admin's server: TTT2 save files on the RPCN host.

Two kinds of call. `GET /player/save` is the read anyone's profile shows, and
needs only the API key. The `/saves/*` routes are an admin's: like rpcn-narco's
admin API they want the admin's password every time, and check it with RPCN
itself; this service passes it through, derived, and keeps nothing. Each
refusal comes back as {"error": "<code>", "message": ...}.
"""

import logging

import httpx

from admin.exceptions import AccountNotFoundError, AdminPasswordError, NotAdminError
from saves.exceptions import (
    BackupNotFoundError, SaveConflictError, SaveNotFoundError, SaveRequestError, SavesUnavailableError,
)
from saves.ports import SaveServer
from shared.rpcn_password import derive_rpcn_password

logger = logging.getLogger(__name__)

_UNAVAILABLE = "세이브 관리 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."

# Both mean "nothing to show" to a profile, which is not a fault to log.
_NOT_FOUND = {"user_not_found", "save_not_found"}

# The refusals an admin can act on. Anything else is a fault between the two
# services, logged here and shown as _UNAVAILABLE.
_REFUSALS = {
    "invalid_credentials": (AdminPasswordError, "비밀번호가 올바르지 않습니다."),
    "forbidden": (NotAdminError, "관리자 권한이 없습니다."),
    "user_not_found": (AccountNotFoundError, "해당 아이디의 계정이 없습니다."),
    "ambiguous_user": (SaveRequestError, "대소문자만 다른 계정이 여럿입니다. 대소문자까지 정확히 입력해 주세요."),
    "save_not_found": (SaveNotFoundError, "이 계정에는 TTT2 세이브가 없습니다."),
    "backup_not_found": (BackupNotFoundError, "해당 백업이 없습니다."),
    "online": (SaveConflictError, "게임에 접속 중인 계정은 수정할 수 없습니다. 접속을 끊은 뒤 다시 시도해 주세요."),
    "save_changed": (SaveConflictError, "미리보기 뒤에 세이브가 바뀌었습니다. 다시 미리보기 해 주세요."),
    "likely_demoted": (SaveConflictError, "이전 floor 뒤에 강등된 캐릭터로 보입니다. 그래도 올리려면 강등 캐릭터 재적용을 선택해 주세요."),
    "online_unknown": (SavesUnavailableError, "접속 여부를 확인할 수 없어 수정하지 않았습니다. 잠시 후 다시 시도해 주세요."),
    "rpcn_unavailable": (SavesUnavailableError, "RPCN 관리 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."),
}


class SaveAdminServer(SaveServer):
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
        path = "/player/save"
        response = await self._send("GET", path, params={"username": npid})
        answer = _json(response)
        if response.status_code == 200 and answer is not None:
            return answer
        if (answer or {}).get("error") in _NOT_FOUND:
            return None
        raise _fault(response, path)

    async def call(self, action: str, admin_username: str, admin_password: str, payload: dict) -> dict:
        body = {**payload, "admin_username": admin_username, "admin_password": derive_rpcn_password(admin_password)}
        path = f"/saves/{action}"
        response = await self._send("POST", path, json=body)
        answer = _json(response)
        if response.status_code == 200 and answer is not None:
            return answer
        raise _refusal(response, answer, path, admin_username)

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Save server not initialized")
        if not self._base_url or not self._api_key:
            logger.error("Save server is not configured: SAVE_ADMIN_URL or SAVE_ADMIN_KEY is empty")
            raise SavesUnavailableError("세이브 관리 기능이 설정되지 않았습니다.")
        try:
            return await self._client.request(method, path, headers={"X-API-Key": self._api_key}, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Save server unreachable at %s%s (%s: %s); check SAVE_ADMIN_URL",
                           self._base_url, path, type(exc).__name__, exc)
            raise SavesUnavailableError(_UNAVAILABLE) from exc


def _json(response: httpx.Response) -> dict | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _refusal(response: httpx.Response, answer: dict | None, path: str, admin_username: str) -> Exception:
    code = (answer or {}).get("error")
    message = (answer or {}).get("message", "")
    if code in _REFUSALS:
        error, text = _REFUSALS[code]
        if code == "forbidden":
            logger.warning("Save server refused %s at %s: not an active RPCN admin", admin_username, path)
        return error(text)
    if code == "invalid_request":
        # Field shapes are checked here first, so this is a rule only the save
        # knows (e.g. a rank the floor table lacks); its message names it.
        return SaveRequestError(f"요청을 처리할 수 없습니다: {message}")
    return _fault(response, path)


def _fault(response: httpx.Response, path: str) -> Exception:
    logger.error("Save server answered %s at %s: %s", response.status_code, path, response.text[:200])
    return SavesUnavailableError(_UNAVAILABLE)
