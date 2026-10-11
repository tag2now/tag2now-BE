from chat import service
from chat.adapters.memory_bus import MemoryChatEventBus
from chat.adapters.memory_repository import MemoryChatRepository

# Enough for a busy evening's conversation. Every stream opens with all of it, so
# this also bounds the snapshot: ~75 KB for typical short lines, ~375 KB if every
# message ran to the 200-character limit.
MAX_KEPT_MESSAGES = 500


async def init_chat() -> None:
    """There is no close_chat: the store and the bus are memory and go with the process."""
    service.configure(MemoryChatRepository(MAX_KEPT_MESSAGES), MemoryChatEventBus())
