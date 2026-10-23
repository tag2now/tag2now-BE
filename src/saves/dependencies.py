"""FastAPI dependencies for saves."""

from fastapi import Request

from saves.service import SavesService


def saves_service(request: Request) -> SavesService:
    return request.app.state.container.saves
