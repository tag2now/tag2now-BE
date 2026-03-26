"""Pydantic request/response DTOs for the community board."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from matching.constants import TTT2_CHARACTERS

VALID_POST_TYPES: set[str] = (
    {"자유", "랭매구인"}
    | {name for name in TTT2_CHARACTERS.values() if name and name != "?"}
)


# --- Requests ---

class SetIdentityRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)


class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=1000)
    post_type: str = "자유"

    @field_validator("post_type")
    @classmethod
    def must_be_valid_post_type(cls, v: str) -> str:
        if v not in VALID_POST_TYPES:
            raise ValueError(f"post_type must be one of: {sorted(VALID_POST_TYPES)}")
        return v


class CreateCommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)
    parent_id: int | None = None


DIRECTION_MAP: dict[str, int] = {"up": 1, "down": -1}


class ThumbRequest(BaseModel):
    direction: str = Field(..., description="up for thumbs up, down for thumbs down")

    @field_validator("direction")
    @classmethod
    def must_be_up_or_down(cls, v: str) -> str:
        if v not in DIRECTION_MAP:
            raise ValueError("direction must be up or down")
        return v

    @property
    def direction_int(self) -> int:
        return DIRECTION_MAP[self.direction]


# --- Responses ---

class PostSummary(BaseModel):
    id: int
    author: str
    title: str
    body: str
    post_type: str = "자유"
    thumbs_up: int
    thumbs_down: int
    created_at: datetime
    comment_count: int = 0


class CommentOut(BaseModel):
    id: int
    post_id: int
    parent_id: int | None
    author: str
    body: str
    created_at: datetime
    replies: list["CommentOut"] = []


class PostDetail(BaseModel):
    id: int
    author: str
    title: str
    body: str
    post_type: str = "자유"
    thumbs_up: int
    thumbs_down: int
    created_at: datetime
    comments: list[CommentOut] = []


class PostListResponse(BaseModel):
    posts: list[PostSummary]
    total: int
    page: int
    page_size: int
