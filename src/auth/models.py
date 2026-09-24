"""Login DTOs, and the account shape the verifier port returns."""

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class VerifiedAccount:
    """What RPCN vouches for once the password matched.

    `username` is RPCN's canonical spelling, which is not necessarily what the
    user typed --- it is the identity every other module keys ownership on.
    """

    username: str
    online_name: str
    avatar_url: str
    admin: bool
    banned: bool


class AuthUser(BaseModel):
    """The signed-in user, as recovered from a verified access token."""

    username: str
    online_name: str
    avatar_url: str = ""
    admin: bool = False


class LoginRequest(BaseModel):
    # RPCN caps usernames at 16 characters; the slack costs nothing and keeps
    # the rule where it belongs, on the RPCN side.
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUser
