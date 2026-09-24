"""Login: RPCN checks the password, this service signs the answer."""

from auth import tokens
from auth.db import get_verifier
from auth.exceptions import AccountBannedError
from auth.models import AuthUser


async def login(username: str, password: str) -> tuple[str, int, AuthUser]:
    account = await get_verifier().verify(username, password)
    if account.banned:
        raise AccountBannedError("이용이 제한된 계정입니다.")
    user = AuthUser(
        username=account.username,
        online_name=account.online_name or account.username,
        avatar_url=account.avatar_url,
        admin=account.admin,
    )
    token, expires_in = tokens.issue_token(user)
    return token, expires_in, user


def authenticate(token: str) -> AuthUser:
    """Recover the user from a token. No I/O: the signature is the whole check.

    A ban placed after login therefore takes effect only when the token expires.
    """
    return tokens.read_token(token)
