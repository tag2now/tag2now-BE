"""The service the saves routes receive, through FastAPI's dependency overrides."""

from unittest.mock import AsyncMock

import pytest

from saves.dependencies import saves_service
from saves.service import SavesService


@pytest.fixture(autouse=True)
def installed():
    """Routes resolve their dependencies before validating a request, so even a
    test that expects a 422 needs a service here; `use_server` replaces it."""
    from app import app

    current = {"service": SavesService(AsyncMock())}
    app.dependency_overrides[saves_service] = lambda: current["service"]
    yield current
    app.dependency_overrides.pop(saves_service, None)
