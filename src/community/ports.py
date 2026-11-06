"""Repository port (interface) for the community board.

Every method runs in the session the service passes, so the service decides the
transaction --- and can put another store's write in the same one.
"""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession


class CommunityRepository(ABC):
    # -- Posts ---------------------------------------------------------------

    @abstractmethod
    async def list_posts(
        self,
        session: AsyncSession,
        page: int,
        page_size: int,
        post_type: str | None = None,
        characters: list[str] | None = None,
    ) -> tuple[list[dict], int]:
        """Return (posts, total_count). Each post dict includes a comment_count key.

        *characters* keeps posts tagged with every one of them, so two names find that team.
        Without *post_type* the list leaves out notices, which are pinned above it and
        fetched with ``post_type=NOTICE_POST_TYPE``.
        """

    @abstractmethod
    async def get_post(self, session: AsyncSession, post_id: int) -> dict:
        """Return a single post or raise PostNotFoundError."""

    @abstractmethod
    async def get_post_comments(self, session: AsyncSession, post_id: int) -> list[dict]:
        """Return flat list of comments for *post_id*, ordered by created_at ASC."""

    @abstractmethod
    async def create_post(
        self,
        session: AsyncSession,
        author: str,
        title: str,
        body: str,
        post_type: str = "자유",
        characters: list[str] | None = None,
        youtube_video_id: str | None = None,
    ) -> dict:
        """Insert a new post and return it."""

    @abstractmethod
    async def update_post(
        self,
        session: AsyncSession,
        post_id: int,
        title: str,
        body: str,
        post_type: str,
        characters: list[str],
        youtube_video_id: str | None,
    ) -> dict:
        """Update editable fields of a post, or raise PostNotFoundError.

        Who may is the service's decision, not the store's."""

    @abstractmethod
    async def delete_post(self, session: AsyncSession, post_id: int) -> None:
        """Delete a post, or raise PostNotFoundError. Who may is the service's decision."""

    # -- Comments ------------------------------------------------------------

    @abstractmethod
    async def create_comment(
        self,
        session: AsyncSession,
        post_id: int,
        author: str,
        body: str,
        parent_id: int | None = None,
    ) -> dict:
        """Add a comment. Raises PostNotFoundError, CommentNotFoundError, NestingDepthError."""

    @abstractmethod
    async def get_comment(self, session: AsyncSession, post_id: int, comment_id: int) -> dict:
        """Return a live comment on *post_id*, or raise CommentNotFoundError."""

    @abstractmethod
    async def delete_comment(self, session: AsyncSession, comment_id: int) -> None:
        """Soft-delete a comment. Who may is the service's decision."""

    # -- Thumbs (posts only) -------------------------------------------------

    @abstractmethod
    async def add_thumb(self, session: AsyncSession, post_id: int, voter: str, direction: int) -> dict:
        """Record a final vote and return thumbs_up, thumbs_down. Raises AlreadyVotedError on a second one."""
