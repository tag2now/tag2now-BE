"""Player save reader factory and lifecycle."""

from saves.adapters.save_admin_server import SaveAdminServerPlayerSaves
from saves.ports import PlayerSaves
from shared.settings import get_settings

_saves: PlayerSaves | None = None


async def init_saves() -> None:
    # The admin save routes' server and key. Unconfigured, it still starts;
    # the route answers 502 and logs why.
    global _saves
    settings = get_settings()
    _saves = SaveAdminServerPlayerSaves(settings.save_admin_url, settings.save_admin_key.get_secret_value(), settings.save_admin_timeout_seconds)
    await _saves.init()


async def close_saves() -> None:
    global _saves
    if _saves:
        await _saves.close()
        _saves = None


def get_player_saves() -> PlayerSaves:
    if _saves is None:
        raise RuntimeError("Player saves not initialized")
    return _saves


def set_player_saves(saves: PlayerSaves | None) -> None:
    """Test seam: swap the adapter without going through settings."""
    global _saves
    _saves = saves
