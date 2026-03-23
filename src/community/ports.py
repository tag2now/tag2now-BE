"""Repository port (interface) for the community board."""

from abc import ABC, abstractmethod


class CommunityRepository(ABC):

    @abstractmethod
    async def init(self) -> None:
        """Initialise the backing store (create tables, pool, etc.)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by the backing store."""

    # -- Posts ---------------------------------------------------------------

    @abstractmethod
    async def list_posts(self, page: int, page_size: int) -> tuple[list[dict], int]:
        """Return (posts, total_count). Each post dict includes a comment_count key."""

    @abstractmethod
    async def get_post(self, post_id: int) -> dict:
        """Return a single post or raise PostNotFoundError."""

    @abstractmethod
    async def get_post_comments(self, post_id: int) -> list[dict]:
        """Return flat list of comments for *post_id*, ordered by created_at ASC."""

    @abstractmethod
    async def create_post(self, author: str, body: str) -> dict:
        """Insert a new post and return it."""

    @abstractmethod
    async def delete_post(self, post_id: int, user: str) -> None:
        """Delete a post owned by *user*, or raise PostNotFoundError / OwnershipError."""

    # -- Comments ------------------------------------------------------------

    @abstractmethod
    async def create_comment(
        self,
        post_id: int,
        author: str,
        body: str,
        parent_id: int | None = None,
    ) -> dict:
        """Add a comment. Raises PostNotFoundError, CommentNotFoundError, NestingDepthError."""

    @abstractmethod
    async def delete_comment(self, comment_id: int, user: str) -> int:
        """Delete a comment owned by *user*. Returns the owning post_id."""

    # -- Thumbs --------------------------------------------------------------

    @abstractmethod
    async def toggle_thumb(
        self, target_type: str, target_id: int, voter: str, direction: int
    ) -> dict:
        """Toggle a thumb vote. Returns dict with thumbs_up, thumbs_down (and post_id for comments)."""
