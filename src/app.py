"""Tekken Tag Tournament 2 RPCN queries and API server.

Credentials are read from environment variables (or a .env file):
  RPCN_USER      - RPCN username (required)
  RPCN_PASSWORD  - RPCN password (required)
  RPCN_TOKEN     - RPCN token   (optional, default: "")
  RPCN_HOST      - server host  (optional, default: np.rpcs3.net)
  RPCN_PORT      - server port  (optional, default: 31313)

API usage:
  RPCN_USER=you RPCN_PASSWORD=secret uvicorn app:app --reload
"""
import json
import logging
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.cache import redis_health_check
from shared.database import init_database, close_database
from shared.rpcn_api import init_rpcn_api, close_rpcn_api
from shared.error_handlers import register_exception_handlers
from admin.db import init_admin, close_admin
from admin.router import router as admin_router
from auth.db import init_auth, close_auth
from auth.router import router as auth_router
from chat.db import init_chat
from chat.router import router as chat_router
from history import init_history_repo, close_history_repo
from history.collector import run_collector, stop_collector
from history.router import router as history_router
from matching.router import router as ttt2_router
from matching.db import init_game_repo, close_game_repo
from community import init_db, close_db
from community.router import router as community_router
from reservation.db import init_db as init_reservation_db, close_db as close_reservation_db
from reservation.router import router as reservation_router
from saves import init_saves, close_saves
from saves.router import router as saves_router, admin_router as saves_admin_router
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
    await init_rpcn_api()
    await init_auth()
    await init_admin()
    await init_saves()
    await init_database()
    await init_db()
    await init_reservation_db()
    await init_history_repo()
    await init_game_repo()
    await init_chat()
    collector_task = asyncio.create_task(run_collector(), name="match-history-collector")
    try:
        yield
    finally:
        await stop_collector(collector_task)
    await close_game_repo()
    await close_history_repo()
    await close_reservation_db()
    await close_db()
    await close_database()
    await close_saves()
    await close_admin()
    await close_auth()
    await close_rpcn_api()


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

register_exception_handlers(app)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
