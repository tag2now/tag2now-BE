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
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.cache import redis_health_check
from shared.database import init_database, close_database
from shared.exceptions import NotFoundError, ForbiddenError, ValidationError, ServiceUnavailableError
from history import init_history_repo, close_history_repo
from history.router import router as history_router
from matching.router import router as ttt2_router
from matching.db import init_game_repo, close_game_repo
from community import init_db, close_db
from community.router import router as community_router
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
    await init_database()
    await init_db()
    await init_history_repo()
    await init_game_repo()
    yield
    await close_game_repo()
    await close_history_repo()
    await close_db()
    await close_database()


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

app.include_router(ttt2_router)
app.include_router(history_router)
app.include_router(community_router, prefix="/community", tags=["community"])


@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request, exc):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ServiceUnavailableError)
async def service_unavailable_handler(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
