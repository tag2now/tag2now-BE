"""Domain events and simple in-process event bus for tekken_tt2."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from tekken_tt2.models import RoomType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


@dataclass
class MatchmakingDetected:
    """A player entered matchmaking (their solo room disappeared)."""
    npid: str
    online_name: str
    room_type: RoomType
    timestamp: float


@dataclass
class MatchmakingResolved:
    """A player left matchmaking."""
    npid: str
    reason: str  # "found_opponent" | "rejoined_room" | "expired"
    timestamp: float


@dataclass
class ActivitySnapshot:
    """A room snapshot was taken — contains player presence data."""
    player_npids: list[str] = field(default_factory=list)
    total_players: int = 0


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

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
