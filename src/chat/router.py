from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from auth.dependencies import current_user
from auth.models import AuthUser
from chat import models, service
from chat.domain import ChatEvent, Deleted, Posted

router = APIRouter(prefix="/chat", tags=["Chat"])


def _to_sse(event: ChatEvent) -> ServerSentEvent:
    match event:
        case Posted(message):
            return ServerSentEvent(event="message", data=models.ChatMessageOut.model_validate(message))
        case Deleted(message_id):
            return ServerSentEvent(event="delete", data=models.DeletedOut(id=message_id))


@router.get("/stream", response_class=EventSourceResponse)
async def stream() -> AsyncIterable[ServerSentEvent]:
    """Today's chat, then every change to it as it happens. Public.

    Opens with a `snapshot` event holding today's messages, then sends
    `message` and `delete` events. A reconnect gets a fresh snapshot rather
    than resuming from `Last-Event-ID`: ids restart with the process, and a
    deletion missed while disconnected is only visible in a whole new list.
    The client replaces its list on every snapshot.
    """
    # Subscribe before reading the snapshot. A store that does real I/O hands
    # the event loop to other requests mid-read; a message posted then is in
    # neither the snapshot nor, if we subscribed only afterwards, the stream.
    # Anything that lands in both is deduplicated by id on the client.
    async with service.subscribe() as events:
        messages = await service.todays_messages()
        yield ServerSentEvent(event="snapshot", data=[models.ChatMessageOut.model_validate(m) for m in messages])
        async for event in events:
            yield _to_sse(event)


@router.post("/messages", response_model=models.ChatMessageOut, status_code=201)
async def post_message(request: models.PostMessageRequest, user: AuthUser = Depends(current_user)):
    return await service.post_message(subject=user.username, display_name=user.online_name, body=request.body)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(message_id: int, user: AuthUser = Depends(current_user)):
    """The author's own message, or any message for an admin."""
    await service.delete_message(message_id, subject=user.username, admin=user.admin)
    return Response(status_code=204)
