"""Stateless access tokens: HS256 JWTs signed with `jwt_secret`.

Nothing is stored. A token is valid until it expires, so signing out is the
client discarding it; rotating the secret is the only way to revoke early, and
it revokes everyone.
"""

from datetime import datetime, timedelta, timezone

import jwt

from auth.exceptions import AuthUnavailableError, InvalidTokenError
from auth.models import AuthUser
from shared.settings import get_settings

_ALGORITHM = "HS256"
_ISSUER = "tag2now"
# RFC 7518 §3.2: an HS256 key must be at least as long as the hash output.
_MIN_SECRET_BYTES = 32


def _secret() -> str:
    secret = get_settings().jwt_secret.get_secret_value()
    if len(secret.encode()) < _MIN_SECRET_BYTES:
        raise AuthUnavailableError("로그인이 설정되지 않았습니다.")
    return secret


def issue_token(user: AuthUser, now: datetime | None = None) -> tuple[str, int]:
    """Return the token and its lifetime in seconds."""
    ttl = get_settings().jwt_ttl_seconds
    issued_at = now or datetime.now(timezone.utc)
    claims = {
        "iss": _ISSUER,
        "sub": user.username,
        "name": user.online_name,
        "avatar": user.avatar_url,
        "admin": user.admin,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM), ttl


def read_token(token: str) -> AuthUser:
    secret = _secret()
    try:
        claims = jwt.decode(
            token, secret, algorithms=[_ALGORITHM], issuer=_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        return AuthUser(
            username=claims["sub"],
            online_name=claims.get("name") or claims["sub"],
            avatar_url=claims.get("avatar", ""),
            admin=bool(claims.get("admin", False)),
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("로그인이 만료되었습니다. 다시 로그인해 주세요.") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise InvalidTokenError("로그인 정보가 올바르지 않습니다. 다시 로그인해 주세요.") from exc
