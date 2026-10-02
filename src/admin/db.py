"""Account admin factory and lifecycle."""

from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.ports import AccountAdmin
from shared.rpcn_api import get_rpcn_api

_admin: AccountAdmin | None = None


async def init_admin() -> None:
    # Login's client: the same API server and key answer both. When they are
    # empty init_auth has already warned, and the routes answer 502.
    global _admin
    _admin = RpcnApiServerAccountAdmin(get_rpcn_api())


async def close_admin() -> None:
    global _admin
    _admin = None


def get_account_admin() -> AccountAdmin:
    if _admin is None:
        raise RuntimeError("Account admin not initialized")
    return _admin


def set_account_admin(admin: AccountAdmin | None) -> None:
    """Test seam: swap the adapter without going through settings."""
    global _admin
    _admin = admin
