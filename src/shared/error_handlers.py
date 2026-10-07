"""How domain exceptions and request-schema violations become HTTP answers.

Services raise the exceptions in `shared/exceptions.py` and know nothing of
status codes; this module is the one place that does. `app.py` only calls
`register_exception_handlers(app)`.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)

# A new domain exception needs one line here. Starlette picks a handler by
# walking the raised exception's MRO, so a subclass --- NotAdminError,
# InvalidTokenError --- answers with its base's status.
_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ForbiddenError: 403,
    ValidationError: 400,
    ConflictError: 409,
    RateLimitedError: 429,
    ServiceUnavailableError: 502,
}


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type, status in _STATUS.items():
        app.add_exception_handler(exc_type, _answer_with(status))
    app.add_exception_handler(UnauthorizedError, _unauthorized)
    app.add_exception_handler(RequestValidationError, _request_validation)


def _answer_with(status: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


async def _unauthorized(request: Request, exc: Exception) -> JSONResponse:
    """401 is the one status that must say how to authenticate (RFC 9110)."""
    return JSONResponse(status_code=401, content={"detail": str(exc)}, headers={"WWW-Authenticate": "Bearer"})


# Field labels for request-schema violations, so a 422 names the input a user
# can actually see rather than the wire field. Every field of every *Request
# model belongs here: a field missing from this map falls through to the
# generic message --- which is what once made "입력값을 확인해 주세요." the
# answer to a too-long username, whose field was missing here.
_FIELD_LABELS = {
    "username": "아이디",
    "password": "비밀번호",
    "title": "제목",
    "body": "내용",
    "post_type": "게시글 종류",
    "characters": "캐릭터",
    "youtube_video_id": "YouTube 영상 링크",
    "parent_id": "상위 댓글",
    "direction": "추천 방향",
    "start_time": "시작 시각",
    "match_type": "매치 종류",
    "capacity": "모집 인원",
    "ranks": "보유 계급",
    "memo": "메모",
    "all_chars": "전체 캐릭터 표시",
    "n": "개수",
    "char": "캐릭터",
    "rank": "계급",
    "points": "점수",
    "dry_run": "미리보기",
    "expect_sha256": "세이브 확인값",
    "fix_points": "점수 보정",
    "refloor": "강등 캐릭터 재적용",
    "label": "백업 이름",
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


async def _request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Keep FastAPI's 422 but answer with one message instead of an error array.

    Pydantic reports every violation; a form shows one line. The first error
    that yields a specific sentence wins, so the user is told the concrete rule
    ("메모는 140자를 넘을 수 없습니다.") rather than that something, somewhere,
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
