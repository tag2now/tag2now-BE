"""Pydantic request/response DTOs for the community board."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from matching.constants import TTT2_CHARACTERS

VALID_POST_TYPES: set[str] = (
    {"자유", "건의", "공략"}
    | {name for name in TTT2_CHARACTERS.values() if name and name != "?"}
)


# --- Requests ---

class SetIdentityRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)


class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    body: str = Field(..., min_length=1, max_length=1000)
    post_type: str = "자유"
    youtube_video_id: str | None = Field(default=None, min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")

    @field_validator("post_type")
    @classmethod
    def must_be_valid_post_type(cls, v: str) -> str:
        if v not in VALID_POST_TYPES:
            # Not enumerated: VALID_POST_TYPES is the three board types plus
            # every character name, and a 60-item list helps nobody.
            raise ValueError("게시글 종류 값을 확인해 주세요.")
        return v


class UpdatePostRequest(CreatePostRequest):
    """The edit form submits all editable fields, including an explicit video removal."""
    post_type: str
    youtube_video_id: str | None = Field(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")

    @field_validator("title", "body")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


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
            raise ValueError("추천 방향 값을 확인해 주세요.")
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
    youtube_video_id: str | None = Field(default=None, min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")
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
    youtube_video_id: str | None = Field(default=None, min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")
    thumbs_up: int
    thumbs_down: int
    created_at: datetime
    comments: list[CommentOut] = []


class PostListResponse(BaseModel):
    posts: list[PostSummary]
    total: int
    page: int
    page_size: int
