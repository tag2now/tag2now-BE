"""FastAPI dependencies for streaming channels."""

from fastapi import Request

from streaming.service import StreamingService


def streaming_service(request: Request) -> StreamingService:
    return request.app.state.container.streaming
