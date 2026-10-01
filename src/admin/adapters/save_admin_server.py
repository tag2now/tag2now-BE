"""tag2now-save-admin's server (`/saves/*`): TTT2 save files on the RPCN host.

Like rpcn-narco's admin API it wants the admin's password on every call, and
checks it with RPCN itself; this service passes it through, derived, and keeps
nothing. Each refusal comes back as {"error": "<code>", "message": ...}.
"""

import logging

import httpx

from admin.exceptions import (
    AccountNotFoundError, AdminPasswordError, AdminUnavailableError, BackupNotFoundError, NotAdminError,
    SaveConflictError, SaveNotFoundError, SaveRequestError,
)
from admin.ports import SaveAdmin
from shared.rpcn_password import derive_rpcn_password

logger = logging.getLogger(__name__)

_UNAVAILABLE = "세이브 관리 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."

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
    "online_unknown": (AdminUnavailableError, "접속 여부를 확인할 수 없어 수정하지 않았습니다. 잠시 후 다시 시도해 주세요."),
    "rpcn_unavailable": (AdminUnavailableError, "RPCN 관리 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."),
}


class SaveAdminServer(SaveAdmin):
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

    async def call(self, action: str, admin_username: str, admin_password: str, payload: dict) -> dict:
        if self._client is None:
            raise RuntimeError("Save admin not initialized")
        if not self._base_url or not self._api_key:
            logger.error("Save admin is not configured: SAVE_ADMIN_URL or SAVE_ADMIN_KEY is empty")
            raise AdminUnavailableError("세이브 관리 기능이 설정되지 않았습니다.")
        body = {**payload, "admin_username": admin_username, "admin_password": derive_rpcn_password(admin_password)}
        path = f"/saves/{action}"
        try:
            response = await self._client.post(path, json=body, headers={"X-API-Key": self._api_key})
        except httpx.HTTPError as exc:
            logger.warning("Save admin unreachable at %s%s (%s: %s); check SAVE_ADMIN_URL",
                           self._base_url, path, type(exc).__name__, exc)
            raise AdminUnavailableError(_UNAVAILABLE) from exc

        answer = _json(response)
        if response.status_code == 200 and answer is not None:
            return answer
        raise _refusal(response, answer, path, admin_username)


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
            logger.warning("Save admin refused %s at %s: not an active RPCN admin", admin_username, path)
        return error(text)
    if code == "invalid_request":
        # Field shapes are checked here first, so this is a rule only the save
        # knows (e.g. a rank the floor table lacks); its message names it.
        return SaveRequestError(f"요청을 처리할 수 없습니다: {message}")
    logger.error("Save admin answered %s at %s: %s", response.status_code, path, response.text[:200])
    return AdminUnavailableError(_UNAVAILABLE)
