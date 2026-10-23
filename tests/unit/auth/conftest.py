"""The service the auth routes receive, through FastAPI's dependency overrides."""

from unittest.mock import AsyncMock

import pytest

from auth.dependencies import auth_service
from auth.service import AuthService


@pytest.fixture(autouse=True)
def installed():
    """Routes resolve their dependencies before validating a request, so even a
    test that expects a 422 needs a service here; the adapter fixture replaces it."""
    from app import app

    current = {"service": AuthService(AsyncMock())}
    app.dependency_overrides[auth_service] = lambda: current["service"]
    yield current
    app.dependency_overrides.pop(auth_service, None)
