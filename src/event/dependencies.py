"""FastAPI dependencies for the rank event."""

from fastapi import Request

from event.service import EventService


def event_service(request: Request) -> EventService:
    return request.app.state.container.event
