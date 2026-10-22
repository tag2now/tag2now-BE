"""FastAPI router for the community board."""

from fastapi import APIRouter, Depends, Query

from auth.dependencies import current_user
from auth.models import AuthUser
from community import models, service

router = APIRouter()


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

@router.get("/posts", response_model=models.PostListResponse)
async def list_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    post_type: str | None = Query(None),
    characters: list[str] = Query([], max_length=models.MAX_POST_CHARACTERS),
):
    return await service.list_posts(page, page_size, post_type, characters)


@router.post("/posts", status_code=201)
async def create_post(req: models.CreatePostRequest, user: AuthUser = Depends(current_user)):
    return await service.create_post(user, req.title, req.body, req.post_type, req.characters, req.youtube_video_id)


@router.get("/posts/{post_id}", response_model=models.PostDetail)
async def get_post(post_id: int):
    return await service.get_post(post_id)


@router.patch("/posts/{post_id}", response_model=models.PostSummary)
async def update_post(post_id: int, req: models.UpdatePostRequest, user: AuthUser = Depends(current_user)):
    return await service.update_post(post_id, user, req.title, req.body, req.post_type, req.characters, req.youtube_video_id)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: int, user: AuthUser = Depends(current_user)):
    await service.delete_post(post_id, user)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@router.post("/posts/{post_id}/comments", status_code=201)
async def create_comment(post_id: int, req: models.CreateCommentRequest, user: AuthUser = Depends(current_user)):
    return await service.create_comment(post_id, user, req.body, req.parent_id)


# ---------------------------------------------------------------------------
# Thumbs (posts only)
# ---------------------------------------------------------------------------

@router.post("/posts/{post_id}/thumb")
async def thumb_post(post_id: int, req: models.ThumbRequest, user: AuthUser = Depends(current_user)):
    return await service.toggle_thumb(post_id, user, req.direction_int)
