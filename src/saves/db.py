"""Save server factory and lifecycle."""

from saves.adapters.save_admin_server import SaveAdminServer
from saves.ports import SaveServer
from shared.settings import get_settings

_server: SaveServer | None = None


async def init_saves() -> None:
    # Unconfigured, it still starts; the save routes answer 502 and log why.
    global _server
    settings = get_settings()
    _server = SaveAdminServer(settings.save_admin_url, settings.save_admin_key.get_secret_value(), settings.save_admin_timeout_seconds)
    await _server.init()


async def close_saves() -> None:
    global _server
    if _server:
        await _server.close()
        _server = None


def get_save_server() -> SaveServer:
    if _server is None:
        raise RuntimeError("Save server not initialized")
    return _server


def set_save_server(server: SaveServer | None) -> None:
    """Test seam: swap the adapter without going through settings."""
    global _server
    _server = server
