"""The service the admin routes receive, through FastAPI's dependency overrides."""

from unittest.mock import AsyncMock

import pytest

from admin.dependencies import admin_service
from admin.service import AdminService


@pytest.fixture(autouse=True)
def installed():
    """Routes resolve their dependencies before validating a request, so even a
    test that expects a 422 needs a service here; the adapter fixture replaces it."""
    from app import app

    current = {"service": AdminService(AsyncMock())}
    app.dependency_overrides[admin_service] = lambda: current["service"]
    yield current
    app.dependency_overrides.pop(admin_service, None)
