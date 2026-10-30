"""FastAPI dependencies for chat."""

from fastapi import Request

from chat.service import ChatService


def chat_service(request: Request) -> ChatService:
    return request.app.state.container.chat
