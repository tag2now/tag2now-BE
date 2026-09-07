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
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.cache import redis_health_check
from shared.database import init_database, close_database
from shared.exceptions import NotFoundError, ForbiddenError, ValidationError, ServiceUnavailableError
from history import init_history_repo, close_history_repo
from history.collector import run_collector, stop_collector
from history.router import router as history_router
from matching.router import router as ttt2_router
from matching.db import init_game_repo, close_game_repo
from community import init_db, close_db
from community.router import router as community_router
from reservation.db import init_db as init_reservation_db, close_db as close_reservation_db
from reservation.router import router as reservation_router
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
    await init_reservation_db()
    await init_history_repo()
    await init_game_repo()
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
app.include_router(reservation_router)


@app.exception_handler(NotFoundError)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request, exc):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Field labels for request-schema violations, so a 422 names the input a user
# can actually see rather than the wire field. Every field of every *Request
# model belongs here: a field missing from this map falls through to the
# generic message, which is what made "입력값을 확인해 주세요." the answer to a
# too-long username --- `name` was absent while `display_name` was present.
_FIELD_LABELS = {
    "name": "유저명",
    "display_name": "유저명",
    "title": "제목",
    "body": "내용",
    "post_type": "게시글 종류",
    "parent_id": "상위 댓글",
    "direction": "추천 방향",
    "start_time": "시작 시각",
    "match_type": "매치 종류",
    "capacity": "모집 인원",
    "ranks": "보유 계급",
    "memo": "메모",
}


def _has_final_consonant(word: str) -> bool:
    """True when the last character is a Hangul syllable ending in a consonant."""
    last = word[-1]
    return "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0


def _topic(word: str) -> str:
    """은/는, chosen by the last syllable, so labels do not read "메모은(는)"."""
    return f"{word}은" if _has_final_consonant(word) else f"{word}는"


def _object(word: str) -> str:
    """을/를, same rule."""
    return f"{word}을" if _has_final_consonant(word) else f"{word}를"


def _describe(error: dict) -> str | None:
    """Turn one pydantic error into a sentence naming the rule it broke.

    Returns None when the error type has no specific phrasing, so the caller can
    fall back to naming the field alone.
    """
    # FastAPI prefixes body-field locations with the literal "body", which is
    # also a field name here --- reading loc front-to-back labelled every
    # username error "내용". The field is the last string in loc, so search from
    # the end.
    label = next(
        (_FIELD_LABELS[loc] for loc in reversed(error["loc"]) if isinstance(loc, str) and loc in _FIELD_LABELS),
        None,
    )
    if label is None:
        return None

    kind = error.get("type", "")
    ctx = error.get("ctx") or {}

    if kind in ("missing", "string_too_short") and ctx.get("min_length", 1) <= 1:
        return f"{_object(label)} 입력해 주세요."
    if kind == "string_too_short":
        return f"{_topic(label)} {ctx['min_length']}자 이상이어야 합니다."
    if kind == "string_too_long":
        return f"{_topic(label)} {ctx['max_length']}자를 넘을 수 없습니다."
    if kind == "too_short":
        return f"{_object(label)} {ctx['min_length']}개 이상 선택해 주세요."
    if kind == "too_long":
        return f"{_topic(label)} {ctx['max_length']}개를 넘을 수 없습니다."
    if kind in ("greater_than_equal", "greater_than"):
        return f"{_topic(label)} {ctx['ge'] if kind.endswith('equal') else ctx['gt']} 이상이어야 합니다."
    if kind in ("less_than_equal", "less_than"):
        return f"{_topic(label)} {ctx['le'] if kind.endswith('equal') else ctx['lt']} 이하여야 합니다."
    # A @field_validator raising ValueError arrives as value_error. Those
    # messages are written for the user and state the rule --- that ranks
    # cannot repeat, which post types exist --- so they beat anything
    # reconstructed from the field name. Falling back to the field alone here
    # would let a vague error mask a specific one reported after it.
    if kind == "value_error" and (message := str(ctx.get("error", "")).strip()):
        return message
    return f"{label} 값을 확인해 주세요."


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request, exc):
    """Keep FastAPI's 422 but answer with one message instead of an error array.

    Pydantic reports every violation; a form shows one line. The first error
    that yields a specific sentence wins, so the user is told the concrete rule
    ("유저명은 50자를 넘을 수 없습니다.") rather than that something, somewhere,
    was wrong.
    """
    for error in exc.errors():
        described = _describe(error)
        if described:
            return JSONResponse(status_code=422, content={"detail": described})

    fields = {loc for error in exc.errors() for loc in error["loc"] if isinstance(loc, str)}
    labels = [label for field, label in _FIELD_LABELS.items() if field in fields]
    detail = f"{', '.join(labels)} 값을 확인해 주세요." if labels else "입력값을 확인해 주세요."
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(ServiceUnavailableError)
async def service_unavailable_handler(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}
