"""FastAPI dependencies other routers use to learn who is calling."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import service
from auth.exceptions import InvalidTokenError
from auth.models import AuthUser

# auto_error=False: a missing header must reach our 401 handler, not FastAPI's
# own 403, so every unauthenticated answer looks the same to the client.
_bearer = HTTPBearer(auto_error=False, description="`POST /auth/login`의 access_token")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> AuthUser:
    """The signed-in user, or 401."""
    if credentials is None:
        raise InvalidTokenError("로그인이 필요합니다.")
    return service.authenticate(credentials.credentials)


def optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> AuthUser | None:
    """The signed-in user, or None when no token was sent. A bad token is still 401."""
    if credentials is None:
        return None
    return service.authenticate(credentials.credentials)
