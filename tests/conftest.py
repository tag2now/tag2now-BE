"""Fixtures shared by unit and integration tests."""

import os

import pytest

# Signed-in routes need a key to sign test tokens with. Set before any test
# module imports shared.settings, whose get_settings() is cached for the run; an
# environment variable outranks the profile's env file, so this also holds
# locally, unless JWT_SECRET is already exported.
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-bytes-long")


@pytest.fixture
def auth_headers():
    """Build Authorization headers for a user, without asking RPCN.

    auth_headers("alice") signs a token the app accepts as alice; each call can
    name a different user, which is how ownership tests play two people.
    """
    from auth.models import AuthUser
    from auth.tokens import issue_token

    def make(username: str = "tester", online_name: str | None = None) -> dict[str, str]:
        token, _ = issue_token(AuthUser(username=username, online_name=online_name or username))
        return {"Authorization": f"Bearer {token}"}

    return make
