"""Tekken Tag Tournament 2 RPCN queries and API server.

Credentials are read from environment variables (or a .env file):
  RPCN_USER      - RPCN username (required)
  RPCN_PASSWORD  - RPCN password (required)
  RPCN_TOKEN     - RPCN token   (optional, default: "")
  RPCN_HOST      - server host  (optional, default: np.rpcs3.net)
  RPCN_PORT      - server port  (optional, default: 31313)

API usage:
  RPCN_USER=you RPCN_PASSWORD=secret uvicorn tekken_tt2.app:app --reload
"""
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.cache import redis_health_check
from shared.exceptions import NotFoundError, ForbiddenError, ValidationError, ServiceUnavailableError
from tekken_tt2.rpcn_lifecycle import shutdown_client
from tekken_tt2.router import router as ttt2_router
from tekken_tt2 import activity_tracker
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
    await init_db()
    await activity_tracker.init()
    yield
    await activity_tracker.close()
    await close_db()
    shutdown_client()


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
