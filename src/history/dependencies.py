"""FastAPI dependencies for history and statistics."""

from fastapi import Request

from history.service import HistoryService


def history_service(request: Request) -> HistoryService:
    return request.app.state.container.history
