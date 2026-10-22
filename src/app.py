"""The ASGI app: every module's router, and a lifespan that builds the services
(container.py) and runs the collector. How to run it is in CLAUDE.md."""
import json
import logging
import os
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from container import build_container
from shared.cache import redis_health_check
from shared.error_handlers import register_exception_handlers
from admin.router import router as admin_router
from auth.router import router as auth_router
from chat.router import router as chat_router
from history.collector import run_collector, stop_collector
from history.router import router as history_router
from matching.router import router as ttt2_router
from community.router import router as community_router
from reservation.router import router as reservation_router
from saves.router import router as saves_router, admin_router as saves_admin_router
from streaming.router import router as streaming_router, admin_router as streaming_admin_router
from shared.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

logger.info("Settings:\n%s", json.dumps(get_settings().model_dump(), indent=2, default=str))

try:
    redis_health_check()
except Exception:
    logger.critical("Shutting down: Redis is unavailable")
    os._exit(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        app.state.container = await build_container(stack)
        collector_task = asyncio.create_task(run_collector(), name="match-history-collector")
        # Registered last, so it is cancelled before anything it reads from closes.
        stack.push_async_callback(stop_collector, collector_task)
        yield


app = FastAPI(
    title="Tekken Tag Tournament 2 RPCN API",
    description="Live data from the RPCN multiplayer server for TTT2.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(saves_admin_router)
app.include_router(ttt2_router)
app.include_router(history_router)
app.include_router(community_router, prefix="/community", tags=["community"])
app.include_router(reservation_router)
app.include_router(saves_router)
app.include_router(chat_router)
app.include_router(streaming_router)
app.include_router(streaming_admin_router)

register_exception_handlers(app)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
