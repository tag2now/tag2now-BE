from chat import service
from chat.adapters.memory_bus import MemoryChatEventBus
from chat.adapters.postgresql import PostgresChatRepository
from shared.database import get_session_factory

# Enough for two busy evenings' conversation. Every stream opens with all of it, so
# this bounds the snapshot: ~75 KB for typical short lines, ~375 KB if every
# message ran to the 200-character limit.
MAX_LISTED_MESSAGES = 500


async def init_chat() -> None:
    """Needs init_database first. There is no close_chat: the shared database
    lifecycle owns the engine, and the bus is memory and goes with the process."""
    service.configure(PostgresChatRepository(get_session_factory(), MAX_LISTED_MESSAGES), MemoryChatEventBus())
