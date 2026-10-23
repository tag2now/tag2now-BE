"""The composition root: builds every module's services once, at startup.

Routes receive a service through `Depends` (each module's `dependencies.py`
reads it from `app.state.container`); code outside a request, such as the
collector, is handed one by the lifespan.
"""

from contextlib import AsyncExitStack
from dataclasses import dataclass

from admin.db import close_admin, init_admin
from auth.db import close_auth, init_auth
from chat.db import init_chat
from community.adapters.postgresql import PostgresCommunityRepository
from community.service import CommunityService
from history.db import close_history_repo, init_history_repo
from matching.db import close_game_repo, init_game_repo
from reservation.adapters.postgresql import PostgresReservationRepository
from reservation.service import ReservationService
from saves.db import close_saves, init_saves
from shared.database import close_database, get_session_factory, init_database
from shared.rpcn_api import close_rpcn_api, init_rpcn_api
from streaming.db import close_streaming, init_streaming


async def _no_close() -> None:
    pass


# Modules still initialised through module-level state, in dependency order.
_LIFECYCLES = (
    (init_rpcn_api, close_rpcn_api),
    (init_auth, close_auth),
    (init_admin, close_admin),
    (init_saves, close_saves),
    (init_database, close_database),
    (init_history_repo, close_history_repo),
    (init_game_repo, close_game_repo),
    (init_chat, _no_close),
    (init_streaming, close_streaming),
)


@dataclass
class Container:
    community: CommunityService
    reservations: ReservationService


async def build_container(stack: AsyncExitStack) -> Container:
    """Open everything in order, registering each close on `stack`, so a failure
    part-way closes exactly what was opened before it."""
    for init, close in _LIFECYCLES:
        await init()
        stack.push_async_callback(close)
    sessions = get_session_factory()
    return Container(
        community=CommunityService(PostgresCommunityRepository(sessions)),
        reservations=ReservationService(PostgresReservationRepository(sessions)),
    )
