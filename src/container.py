"""The composition root: builds every module's services once, at startup.

Routes receive a service through `Depends` (each module's `dependencies.py`
reads it from `app.state.container`); code outside a request, such as the
collector, is handed one by the lifespan.
"""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass

from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.service import AdminService
from auth.adapters.rpcn_api_server import RpcnApiServerAccountVerifier
from auth.service import AuthService
from chat.db import init_chat
from community.adapters.postgresql import PostgresCommunityRepository
from community.service import CommunityService
from history.db import close_history_repo, init_history_repo
from matching import service as matching_service
from matching.db import close_game_repo, init_game_repo
from reservation.adapters.postgresql import PostgresReservationRepository
from reservation.service import ReservationService
from saves.adapters.save_admin_server import SaveAdminServer
from saves.service import SavesService
from shared.database import close_database, get_session_factory, init_database
from shared.rpcn_api import RpcnApiClient
from shared.settings import get_settings
from streaming.adapters.chzzk import ChzzkPlatform
from streaming.adapters.postgresql import PostgresStreamChannelRepository
from streaming.service import StreamingService

logger = logging.getLogger(__name__)


async def _no_close() -> None:
    pass


# Modules still initialised through module-level state, in dependency order.
_LIFECYCLES = (
    (init_database, close_database),
    (init_history_repo, close_history_repo),
    (init_game_repo, close_game_repo),
    (init_chat, _no_close),
)


@dataclass
class Container:
    auth: AuthService
    admin: AdminService
    community: CommunityService
    reservations: ReservationService
    saves: SavesService
    streaming: StreamingService


async def build_container(stack: AsyncExitStack) -> Container:
    """Open everything in order, registering each close on `stack`, so a failure
    part-way closes exactly what was opened before it."""
    for init, close in _LIFECYCLES:
        await init()
        stack.push_async_callback(close)
    settings = get_settings()

    # rpcn-narco's API server answers both login and moderation, with one key.
    # Unconfigured, it still starts: login and every signed-in route answer 502.
    if not (settings.rpcn_api_server_url and settings.rpcn_api_server_key.get_secret_value()
            and settings.jwt_secret.get_secret_value()):
        logger.warning("Login is not configured: set RPCN_API_SERVER_URL, RPCN_API_SERVER_KEY and JWT_SECRET")
    rpcn_api = RpcnApiClient(
        settings.rpcn_api_server_url, settings.rpcn_api_server_key.get_secret_value(),
        settings.rpcn_api_server_timeout_seconds,
    )
    await rpcn_api.init()
    stack.push_async_callback(rpcn_api.close)

    # Unconfigured, it still starts; the save routes answer 502 and log why.
    save_server = SaveAdminServer(
        settings.save_admin_url, settings.save_admin_key.get_secret_value(), settings.save_admin_timeout_seconds,
    )
    await save_server.init()
    stack.push_async_callback(save_server.close)

    chzzk = ChzzkPlatform(settings.chzzk_api_url, settings.chzzk_timeout_seconds)
    await chzzk.init()
    stack.push_async_callback(chzzk.close)

    sessions = get_session_factory()
    streaming = StreamingService(PostgresStreamChannelRepository(), chzzk, sessions)
    matching_service.use_streaming(streaming)
    return Container(
        auth=AuthService(RpcnApiServerAccountVerifier(rpcn_api)),
        admin=AdminService(RpcnApiServerAccountAdmin(rpcn_api)),
        community=CommunityService(PostgresCommunityRepository(sessions)),
        reservations=ReservationService(PostgresReservationRepository(sessions)),
        saves=SavesService(save_server),
        streaming=streaming,
    )
