"""Simple in-process event bus for cross-module communication."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable

logger = logging.getLogger(__name__)

_handlers: dict[type, list[Callable]] = defaultdict(list)


def subscribe(event_type: type, handler: Callable) -> None:
	"""Register a handler for an event type."""
	_handlers[event_type].append(handler)


def publish(event: object) -> None:
	"""Dispatch an event to all registered handlers.

	Async handlers are scheduled as tasks on the running event loop.
	Sync handlers are called directly. Errors are logged, not raised.
	"""
	for handler in _handlers.get(type(event), []):
		try:
			result = handler(event)
			if asyncio.iscoroutine(result):
				asyncio.get_event_loop().create_task(_safe_async(handler, result))
		except Exception:
			logger.warning("Event handler %s failed", handler.__name__, exc_info=True)


async def _safe_async(handler: Callable, coro) -> None:
	try:
		await coro
	except Exception:
		logger.warning("Async event handler %s failed", handler.__name__, exc_info=True)
