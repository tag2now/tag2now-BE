"""Account admin and save admin factories and lifecycle."""

from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.adapters.save_admin_server import SaveAdminServer
from admin.ports import AccountAdmin, SaveAdmin
from shared.settings import get_settings

_admin: AccountAdmin | None = None
_save_admin: SaveAdmin | None = None


async def init_admin() -> None:
    # Shares login's settings: the same API server and key answer both. When
    # they are empty init_auth has already warned, and the routes answer 502.
    global _admin
    settings = get_settings()
    _admin = RpcnApiServerAccountAdmin(settings.rpcn_api_server_url, settings.rpcn_api_server_key.get_secret_value(), settings.rpcn_api_server_timeout_seconds)
    await _admin.init()
    # Unconfigured, it still starts; its routes answer 502 and log why.
    global _save_admin
    _save_admin = SaveAdminServer(settings.save_admin_url, settings.save_admin_key.get_secret_value(), settings.save_admin_timeout_seconds)
    await _save_admin.init()


async def close_admin() -> None:
    global _admin, _save_admin
    if _save_admin:
        await _save_admin.close()
        _save_admin = None
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


def get_save_admin() -> SaveAdmin:
    if _save_admin is None:
        raise RuntimeError("Save admin not initialized")
    return _save_admin


def set_save_admin(save_admin: SaveAdmin | None) -> None:
    """Test seam: swap the adapter without going through settings."""
    global _save_admin
    _save_admin = save_admin
