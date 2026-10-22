"""Business logic for the community board: rules, read-through caching, and
invalidation after every write."""

import asyncio

from auth.models import AuthUser
from community.exceptions import NoticeAdminOnlyError, OwnershipError
from community.models import NOTICE_POST_TYPE
from community.ports import CommunityRepository
from shared.cache import cache_delete, cache_delete_pattern, cache_get, cache_set
from shared.settings import get_settings


def _ttl() -> int:
    return get_settings().cache_ttl_community


def _list_key(page: int, page_size: int, post_type: str | None, team: list[str]) -> str:
    return f"community:posts:p{page}:s{page_size}:t{post_type or 'all'}:c{'+'.join(team) or 'all'}"


def _post_key(post_id: int) -> str:
    return f"community:post:{post_id}"


def _invalidate_lists() -> None:
    cache_delete_pattern("community:posts:*")


def _invalidate_post(post_id: int) -> None:
    cache_delete(_post_key(post_id))


# ---------------------------------------------------------------------------
# Rules
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


def _nest_replies(comments: list[dict]) -> list[dict]:
    # A reply whose parent is missing is shown as a top-level comment.
    by_id = {c["id"]: {**c, "replies": []} for c in comments}
    top_level = []
    for comment in by_id.values():
        parent = by_id.get(comment["parent_id"]) if comment["parent_id"] else None
        if parent:
            parent["replies"].append(comment)
        else:
            top_level.append(comment)
    return top_level


class CommunityService:
    def __init__(self, repo: CommunityRepository):
        self._repo = repo

    # -- Posts ---------------------------------------------------------------

    async def list_posts(self, page: int, page_size: int, post_type: str | None = None, characters: list[str] | None = None) -> dict:
        # A team is unordered: Jin+Kazuya and Kazuya+Jin share one cache entry.
        team = sorted(set(characters or ()))
        key = _list_key(page, page_size, post_type, team)
        if cached := cache_get(key):
            return cached
        posts, total = await self._repo.list_posts(page, page_size, post_type, team)
        result = {"posts": posts, "total": total, "page": page, "page_size": page_size}
        cache_set(key, result, _ttl())
        return result

    async def get_post(self, post_id: int) -> dict:
        """The post with its comments, each top-level comment carrying its replies."""
        key = _post_key(post_id)
        if cached := cache_get(key):
            return cached
        post, comments = await asyncio.gather(self._repo.get_post(post_id), self._repo.get_post_comments(post_id))
        post["comments"] = _nest_replies(comments)
        cache_set(key, post, _ttl())
        return post

    async def create_post(self, author: AuthUser, title: str, body: str, post_type: str = "자유", characters: list[str] | None = None, youtube_video_id: str | None = None) -> dict:
        ensure_can_use_post_type(post_type, author)
        post = await self._repo.create_post(author.username, title, body, post_type, characters, youtube_video_id)
        _invalidate_lists()
        return post

    async def update_post(self, post_id: int, user: AuthUser, title: str, body: str, post_type: str, characters: list[str], youtube_video_id: str | None) -> dict:
        ensure_can_use_post_type(post_type, user)
        ensure_can_manage_post(await self._repo.get_post(post_id), user)
        post = await self._repo.update_post(post_id, title, body, post_type, characters, youtube_video_id)
        _invalidate_lists()
        _invalidate_post(post_id)
        return post

    async def delete_post(self, post_id: int, user: AuthUser) -> None:
        ensure_can_manage_post(await self._repo.get_post(post_id), user)
        await self._repo.delete_post(post_id)
        _invalidate_lists()
        _invalidate_post(post_id)

    # -- Comments ------------------------------------------------------------

    async def create_comment(self, post_id: int, author: AuthUser, body: str, parent_id: int | None = None) -> dict:
        comment = await self._repo.create_comment(post_id, author.username, body, parent_id)
        _invalidate_post(post_id)
        return comment

    # -- Thumbs (posts only) -------------------------------------------------

    async def toggle_thumb(self, post_id: int, voter: AuthUser, direction: int) -> dict:
        result = await self._repo.toggle_thumb(post_id, voter.username, direction)
        _invalidate_post(post_id)
        return result
