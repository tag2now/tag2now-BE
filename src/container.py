"""The composition root: builds every module's services once, at startup.

Routes receive a service through `Depends` (each module's `dependencies.py`
reads it from `app.state.container`); code outside a request, such as the
collector, is handed one by the lifespan.
"""

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial

from admin.adapters.rpcn_api_server import RpcnApiServerAccountAdmin
from admin.service import AdminService
from auth.adapters.rpcn_api_server import RpcnApiServerAccountVerifier
from auth.service import AuthService
from chat.adapters.memory_bus import MemoryChatEventBus
from chat.adapters.postgresql import PostgresChatRepository
from chat.domain import MAX_LISTED_MESSAGES
from chat.service import ChatService
from community.adapters.postgresql import PostgresCommunityRepository
from community.service import CommunityService
from history.adapters.postgresql import PostgresHistoryAdapter
from history.collector import Collector
from history.service import HistoryService
from matching.adapters.rpcn import RpcnGameServerAdapter
from matching.rpcn_lifecycle import SharedRpcnClient, create_client
from matching.service import MatchingService
from reservation.adapters.postgresql import PostgresReservationRepository
from reservation.service import ReservationService
from saves.adapters.save_admin_server import SaveAdminServer
from saves.service import SavesService
from shared.database import open_database
from shared.rpcn_api import RpcnApiClient
from shared.settings import Settings, get_settings
from streaming.adapters.chzzk import ChzzkPlatform
from streaming.adapters.postgresql import PostgresStreamChannelRepository
from streaming.service import StreamingService

logger = logging.getLogger(__name__)


@dataclass
class Container:
    collector: Collector
    auth: AuthService
    admin: AdminService
    chat: ChatService
    community: CommunityService
    history: HistoryService
    matching: MatchingService
    reservations: ReservationService
    saves: SavesService
    streaming: StreamingService


async def build_container(stack: AsyncExitStack) -> Container:
    """Open everything in order, each entered on `stack` as it opens, so a failure
    part-way closes exactly what was opened before it."""
    settings = get_settings()
    _warn_if_login_unconfigured(settings)

    sessions = await stack.enter_async_context(open_database())
    rpcn_api = await stack.enter_async_context(_rpcn_api(settings))
    save_server = await stack.enter_async_context(_save_server(settings))
    chzzk = await stack.enter_async_context(_chzzk(settings))
    game_server = await stack.enter_async_context(RpcnGameServerAdapter(_rpcn(settings)))

    matching = MatchingService(game_server)
    history = HistoryService(PostgresHistoryAdapter(), sessions)
    return Container(
        collector=Collector(matching, history),
        auth=AuthService(RpcnApiServerAccountVerifier(rpcn_api)),
        admin=AdminService(RpcnApiServerAccountAdmin(rpcn_api)),
        # The bus is memory and goes with the process; nothing to close.
        chat=ChatService(PostgresChatRepository(sessions, MAX_LISTED_MESSAGES), MemoryChatEventBus()),
        community=CommunityService(PostgresCommunityRepository(sessions)),
        history=history,
        matching=matching,
        reservations=ReservationService(PostgresReservationRepository(sessions)),
        saves=SavesService(save_server),
        streaming=StreamingService(PostgresStreamChannelRepository(), chzzk, sessions),
    )


def _warn_if_login_unconfigured(settings: Settings) -> None:
    """Unconfigured, the server still starts: login and every signed-in route answer 502."""
    configured = (
        settings.rpcn_api_server_url
        and settings.rpcn_api_server_key.get_secret_value()
        and settings.jwt_secret.get_secret_value()
    )
    if not configured:
        logger.warning("Login is not configured: set RPCN_API_SERVER_URL, RPCN_API_SERVER_KEY and JWT_SECRET")


def _rpcn_api(settings: Settings) -> RpcnApiClient:
    """rpcn-narco's API server, which answers both login and moderation with one key."""
    return RpcnApiClient(
        settings.rpcn_api_server_url,
        settings.rpcn_api_server_key.get_secret_value(),
        settings.rpcn_api_server_timeout_seconds,
    )


def _save_server(settings: Settings) -> SaveAdminServer:
    """Unconfigured, the server still starts; the save routes answer 502 and log why."""
    return SaveAdminServer(
        settings.save_admin_url,
        settings.save_admin_key.get_secret_value(),
        settings.save_admin_timeout_seconds,
    )


def _chzzk(settings: Settings) -> ChzzkPlatform:
    return ChzzkPlatform(settings.chzzk_api_url, settings.chzzk_timeout_seconds)


def _rpcn(settings: Settings) -> SharedRpcnClient:
    """Connects to RPCN on first use; closing the game server disconnects it."""
    return SharedRpcnClient(
        partial(
            create_client,
            settings.rpcn_host,
            settings.rpcn_port,
            settings.rpcn_user,
            settings.rpcn_password,
            settings.rpcn_token,
            settings.rpcn_metric_enable,
        )
    )
