"""The service the streaming routes receive, through FastAPI's dependency overrides."""

from unittest.mock import AsyncMock

import pytest

from streaming.dependencies import streaming_service
from streaming.service import StreamingService


@pytest.fixture(autouse=True)
def installed():
    """Routes resolve their dependencies before validating a request, so even a
    test that expects a 422 needs a service here; `use_platform` replaces it."""
    from app import app

    current = {"service": StreamingService(AsyncMock(), AsyncMock(), AsyncMock())}
    app.dependency_overrides[streaming_service] = lambda: current["service"]
    yield current
    app.dependency_overrides.pop(streaming_service, None)
