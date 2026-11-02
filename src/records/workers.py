"""Background loops for match records, separate from the collector so a save server
outage costs only these."""

import asyncio
import logging

from records.service import RecordsService
from shared.settings import get_settings

logger = logging.getLogger(__name__)


class SaveCapture:
    def __init__(self, records: RecordsService):
        self._records = records

    async def run(self) -> None:
        """Run immediately, then at the configured interval until cancelled."""
        settings = get_settings()
        if not settings.save_admin_url:
            logger.info("Match records are off: SAVE_ADMIN_URL is empty")
            return
        while True:
            try:
                await self._records.capture()
            except Exception:
                logger.warning("Save capture failed", exc_info=True)
            await asyncio.sleep(settings.save_capture_interval_seconds)


class EventConsumer:
    def __init__(self, records: RecordsService):
        self._records = records

    async def _process(self) -> bool:
        try:
            return await self._records.process_next()
        except Exception:
            logger.warning("Match event processing failed", exc_info=True)
            return False

    async def run(self) -> None:
        """Work through due events, sleeping only when none is left."""
        idle = get_settings().match_event_idle_seconds
        while True:
            if not await self._process():
                await asyncio.sleep(idle)
