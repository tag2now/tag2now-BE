"""Repository factory and lifecycle for matching."""

import logging

from matching.ports import GameServerPort

logger = logging.getLogger(__name__)

_game_repo: GameServerPort | None = None


def _create_game_repo() -> GameServerPort:
    from matching.adapters.rpcn import RpcnGameServerAdapter
    return RpcnGameServerAdapter()


async def init_game_repo() -> None:
    global _game_repo
    _game_repo = _create_game_repo()
    await _game_repo.init()
    logger.info("Game server repository ready")


async def close_game_repo() -> None:
    global _game_repo
    if _game_repo:
        await _game_repo.close()
        _game_repo = None
        logger.info("Game server repository closed")


def get_game_server_repo() -> GameServerPort:
    if _game_repo is None:
        raise RuntimeError("Game server repository not initialized — call init_game_repo() first")
    return _game_repo
