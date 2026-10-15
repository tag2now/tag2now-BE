"""Business logic for the community board — delegates to the repository port."""

from auth.models import AuthUser
from community.db import get_repo
from community.exceptions import NoticeAdminOnlyError, OwnershipError
from community.models import NOTICE_POST_TYPE


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

def ensure_can_use_post_type(post_type: str, user: AuthUser) -> None:
    """A notice is pinned above everyone's posts, so only an admin may write one.

    Trusts the token's admin claim, which can be a token's lifetime old: a
    demoted admin keeps this until it expires.
    """
    if post_type == NOTICE_POST_TYPE and not user.admin:
        raise NoticeAdminOnlyError("공지는 관리자만 작성할 수 있습니다.")


def ensure_can_manage_post(post: dict, user: AuthUser) -> None:
    """A post is its author's to edit or delete; a notice is every admin's.

    Judged by the post as stored, not as the request would leave it, so an
    admin still cannot turn someone else's post into a notice to take it over.
    """
    owns = post["author"] == user.username
    co_admin = post["post_type"] == NOTICE_POST_TYPE and user.admin
    if not (owns or co_admin):
        raise OwnershipError("Not your post")


async def list_posts(page: int, page_size: int, post_type: str | None = None, characters: list[str] | None = None) -> tuple[list[dict], int]:
    return await get_repo().list_posts(page, page_size, post_type, characters)


async def get_post(post_id: int) -> dict:
    return await get_repo().get_post(post_id)


async def get_post_comments(post_id: int) -> list[dict]:
    return await get_repo().get_post_comments(post_id)


async def create_post(author: AuthUser, title: str, body: str, post_type: str = "자유", characters: list[str] | None = None, youtube_video_id: str | None = None) -> dict:
    ensure_can_use_post_type(post_type, author)
    return await get_repo().create_post(author.username, title, body, post_type, characters, youtube_video_id)


async def update_post(post_id: int, user: AuthUser, title: str, body: str, post_type: str, characters: list[str], youtube_video_id: str | None) -> dict:
    ensure_can_use_post_type(post_type, user)
    repo = get_repo()
    ensure_can_manage_post(await repo.get_post(post_id), user)
    return await repo.update_post(post_id, title, body, post_type, characters, youtube_video_id)


async def delete_post(post_id: int, user: AuthUser):
    repo = get_repo()
    ensure_can_manage_post(await repo.get_post(post_id), user)
    await repo.delete_post(post_id)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

async def create_comment(post_id: int, author: str, body: str, parent_id: int | None = None) -> dict:
    return await get_repo().create_comment(post_id, author, body, parent_id)


# ---------------------------------------------------------------------------
# Thumbs (posts only)
# ---------------------------------------------------------------------------

async def toggle_thumb(post_id: int, voter: str, direction: int):
    return await get_repo().toggle_thumb(post_id, voter, direction)
