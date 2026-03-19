"""SQL queries and business logic for the community board."""

from community.db import get_db
from community.exceptions import (
    PostNotFoundError,
    CommentNotFoundError,
    OwnershipError,
    NestingDepthError,
)


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

async def list_posts(page: int, page_size: int) -> tuple[list[dict], int]:
    db = get_db()
    offset = (page - 1) * page_size
    rows = await db.fetch(
        """
        SELECT p.*, COALESCE(c.cnt, 0) AS comment_count,
               COUNT(*) OVER() AS total
        FROM posts p
        LEFT JOIN (SELECT post_id, COUNT(*) AS cnt FROM comments GROUP BY post_id) c
            ON c.post_id = p.id
        ORDER BY p.created_at DESC
        LIMIT $1 OFFSET $2
        """,
        page_size, offset,
    )
    total = rows[0]["total"] if rows else 0
    return [dict(r) for r in rows], total


async def get_post(post_id: int) -> dict:
    db = get_db()
    row = await db.fetchrow("SELECT * FROM posts WHERE id = $1", post_id)
    if row is None:
        raise PostNotFoundError("Post not found")
    return dict(row)


async def get_post_comments(post_id: int) -> list[dict]:
    db = get_db()
    rows = await db.fetch(
        "SELECT * FROM comments WHERE post_id = $1 ORDER BY created_at ASC",
        post_id,
    )
    return [dict(r) for r in rows]


async def create_post(author: str, body: str) -> dict:
    db = get_db()
    row = await db.fetchrow(
        "INSERT INTO posts (author, body) VALUES ($1, $2) RETURNING *",
        author, body,
    )
    return dict(row)


async def delete_post(post_id: int, user: str):
    db = get_db()
    row = await db.fetchrow("SELECT author FROM posts WHERE id = $1", post_id)
    if row is None:
        raise PostNotFoundError("Post not found")
    if row["author"] != user:
        raise OwnershipError("Not your post")
    await db.execute("DELETE FROM posts WHERE id = $1", post_id)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

async def create_comment(post_id: int, author: str, body: str, parent_id: int | None = None) -> dict:
    db = get_db()
    # verify post exists
    row = await db.fetchrow("SELECT id FROM posts WHERE id = $1", post_id)
    if row is None:
        raise PostNotFoundError("Post not found")

    # enforce 1-depth nesting
    if parent_id is not None:
        row = await db.fetchrow(
            "SELECT parent_id FROM comments WHERE id = $1 AND post_id = $2",
            parent_id, post_id,
        )
        if row is None:
            raise CommentNotFoundError("Parent comment not found")
        if row["parent_id"] is not None:
            raise NestingDepthError("Cannot reply to a reply (max 1-depth nesting)")

    row = await db.fetchrow(
        "INSERT INTO comments (post_id, parent_id, author, body) VALUES ($1, $2, $3, $4) RETURNING *",
        post_id, parent_id, author, body,
    )
    return dict(row)


async def delete_comment(comment_id: int, user: str) -> int:
    """Delete a comment. Returns the owning post_id for cache invalidation."""
    db = get_db()
    row = await db.fetchrow("SELECT author, post_id FROM comments WHERE id = $1", comment_id)
    if row is None:
        raise CommentNotFoundError("Comment not found")
    if row["author"] != user:
        raise OwnershipError("Not your comment")
    await db.execute("DELETE FROM comments WHERE id = $1", comment_id)
    return row["post_id"]


# ---------------------------------------------------------------------------
# Thumbs
# ---------------------------------------------------------------------------

async def toggle_thumb(target_type: str, target_id: int, voter: str, direction: int):
    """Toggle a thumb vote. Same direction twice removes it; different direction replaces it."""
    db = get_db()
    table = "posts" if target_type == "post" else "comments"

    async with db.acquire() as conn:
        async with conn.transaction():
            # verify target exists; fetch post_id for cache invalidation
            if target_type == "comment":
                row = await conn.fetchrow("SELECT id, post_id FROM comments WHERE id = $1", target_id)
            else:
                row = await conn.fetchrow("SELECT id FROM posts WHERE id = $1", target_id)
            if row is None:
                if target_type == "post":
                    raise PostNotFoundError(f"{target_type.title()} not found")
                raise CommentNotFoundError(f"{target_type.title()} not found")

            existing = await conn.fetchrow(
                "SELECT direction FROM thumbs WHERE target_type = $1 AND target_id = $2 AND voter = $3",
                target_type, target_id, voter,
            )

            if existing and existing["direction"] == direction:
                # toggle off
                await conn.execute(
                    "DELETE FROM thumbs WHERE target_type = $1 AND target_id = $2 AND voter = $3",
                    target_type, target_id, voter,
                )
            else:
                # insert or replace
                await conn.execute(
                    """
                    INSERT INTO thumbs (target_type, target_id, voter, direction)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(target_type, target_id, voter)
                    DO UPDATE SET direction = excluded.direction
                    """,
                    target_type, target_id, voter, direction,
                )

            # recalculate counts
            counts = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN direction = 1 THEN 1 ELSE 0 END), 0) AS up,
                    COALESCE(SUM(CASE WHEN direction = -1 THEN 1 ELSE 0 END), 0) AS down
                FROM thumbs
                WHERE target_type = $1 AND target_id = $2
                """,
                target_type, target_id,
            )
            up, down = counts["up"], counts["down"]
            await conn.execute(
                f"UPDATE {table} SET thumbs_up = $1, thumbs_down = $2 WHERE id = $3",
                up, down, target_id,
            )

    result = {"thumbs_up": up, "thumbs_down": down}
    if target_type == "comment":
        result["post_id"] = row["post_id"]
    return result
