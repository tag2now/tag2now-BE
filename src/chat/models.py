from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_BODY_LENGTH = 200


class PostMessageRequest(BaseModel):
    # Stripped before the length check, so a line of spaces is "empty" rather
    # than a blank message everyone has to scroll past.
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_BODY_LENGTH)]


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_username: str
    author_online_name: str
    body: str
    created_at: datetime


class DeletedOut(BaseModel):
    id: int
