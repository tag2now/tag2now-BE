"""Repository factory and lifecycle for the history module."""

import logging

from history.ports import HistoryPort
from shared.database import get_session_factory

logger = logging.getLogger(__name__)

_repo: HistoryPort | None = None


def _create_repo() -> HistoryPort:
	from history.adapters.postgresql import PostgresHistoryAdapter
	return PostgresHistoryAdapter(session_factory=get_session_factory())


async def init_history_repo() -> None:
	global _repo
	_repo = _create_repo()
	await _repo.init()

	# Subscribe to matching events
	from history.event_handlers import subscribe_events
	subscribe_events()


async def close_history_repo() -> None:
	global _repo
	if _repo:
		await _repo.close()
		_repo = None


def get_history_repo() -> HistoryPort:
	if _repo is None:
		raise RuntimeError("History repository not initialized — call init_history_repo() first")
	return _repo
