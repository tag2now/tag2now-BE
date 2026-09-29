"""Account admin factory and lifecycle."""

from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.ports import AccountAdmin
from shared.settings import get_settings

_admin: AccountAdmin | None = None


async def init_admin() -> None:
    # Shares login's settings: the same API server and key answer both. When
    # they are empty init_auth has already warned, and the routes answer 502.
    global _admin
    settings = get_settings()
    _admin = RpcnApiServerAccountAdmin(settings.rpcn_api_server_url, settings.rpcn_api_server_key.get_secret_value(), settings.rpcn_api_server_timeout_seconds)
    await _admin.init()


async def close_admin() -> None:
    global _admin
    if _admin:
        await _admin.close()
        _admin = None


def get_account_admin() -> AccountAdmin:
    if _admin is None:
        raise RuntimeError("Account admin not initialized")
    return _admin


def set_account_admin(admin: AccountAdmin | None) -> None:
    """Test seam: swap the adapter without going through settings."""
    global _admin
    _admin = admin
