"""Account verifier factory and lifecycle."""

import logging

from auth.adapters.rpcn_api_server import RpcnApiServerAccountVerifier
from auth.ports import AccountVerifier
from shared.rpcn_api import get_rpcn_api
from shared.settings import get_settings

logger = logging.getLogger(__name__)

_verifier: AccountVerifier | None = None


async def init_auth() -> None:
    global _verifier
    settings = get_settings()
    if not settings.rpcn_api_server_url or not settings.rpcn_api_server_key.get_secret_value() or not settings.jwt_secret.get_secret_value():
        # Everything but login keeps working; login and every signed-in route
        # answer 502 until the settings are filled in.
        logger.warning("Login is not configured: set RPCN_API_SERVER_URL, RPCN_API_SERVER_KEY and JWT_SECRET")
    _verifier = RpcnApiServerAccountVerifier(get_rpcn_api())


async def close_auth() -> None:
    global _verifier
    _verifier = None


def get_verifier() -> AccountVerifier:
    if _verifier is None:
        raise RuntimeError("Account verifier not initialized")
    return _verifier


def set_verifier(verifier: AccountVerifier | None) -> None:
    """Test seam: swap the verifier without going through settings."""
    global _verifier
    _verifier = verifier
