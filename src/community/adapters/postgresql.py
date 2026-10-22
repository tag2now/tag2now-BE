"""SQLAlchemy ORM adapter for the community repository."""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from community.entities import Comment, Post, Thumb
from community.exceptions import CommentNotFoundError, NestingDepthError, PostNotFoundError
from community.models import NOTICE_POST_TYPE
from community.ports import CommunityRepository


def _as_dict(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class PostgresCommunityRepository(CommunityRepository):
    """Community persistence using the application's shared session factory."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        # The shared database lifecycle owns the engine; this only borrows sessions.
        self._sessions = sessions

    # -- Posts ---------------------------------------------------------------

    async def list_posts(self, page, page_size, post_type=None, characters=None):
        # Notices are pinned above the list, so the unfiltered list leaves them out.
        filters = [Post.post_type == post_type if post_type else Post.post_type != NOTICE_POST_TYPE]
        if characters:
            filters.append(Post.characters.contains(characters))

        comment_count = func.count(Comment.id).label("comment_count")
        page_query = (
            select(Post, comment_count)
            .outerjoin(Comment, Comment.post_id == Post.id)
            .where(*filters)
            .group_by(Post.id)
            .order_by(Post.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        async with self._sessions() as session:
            total = await session.scalar(select(func.count()).select_from(Post).where(*filters))
            rows = (await session.execute(page_query)).all()
            return [{**_as_dict(post), "comment_count": count} for post, count in rows], total

    async def get_post(self, post_id):
        async with self._sessions() as session:
            post = await session.get(Post, post_id)
            if post is None:
                raise PostNotFoundError("Post not found")
            return _as_dict(post)

    async def get_post_comments(self, post_id):
        query = select(Comment).where(Comment.post_id == post_id).order_by(Comment.created_at)
        async with self._sessions() as session:
            comments = (await session.scalars(query)).all()
            return [_as_dict(comment) for comment in comments]

    async def create_post(self, author, title, body, post_type="자유", characters=None, youtube_video_id=None):
        post = Post(
            author=author, title=title, body=body, post_type=post_type,
            characters=list(characters or []), youtube_video_id=youtube_video_id,
        )
        async with self._sessions() as session, session.begin():
            session.add(post)
            await session.flush()
            await session.refresh(post)
            return _as_dict(post)

    async def update_post(self, post_id, title, body, post_type, characters, youtube_video_id):
        async with self._sessions() as session, session.begin():
            post = await session.scalar(select(Post).where(Post.id == post_id).with_for_update())
            if post is None:
                raise PostNotFoundError("Post not found")
            post.title = title
            post.body = body
            post.post_type = post_type
            post.characters = list(characters)
            post.youtube_video_id = youtube_video_id
            await session.flush()
            comment_count = await session.scalar(
                select(func.count()).select_from(Comment).where(Comment.post_id == post_id)
            )
            return {**_as_dict(post), "comment_count": comment_count}

    async def delete_post(self, post_id):
        async with self._sessions() as session, session.begin():
            post = await session.get(Post, post_id)
            if post is None:
                raise PostNotFoundError("Post not found")
            await session.delete(post)

    # -- Comments ------------------------------------------------------------

    async def create_comment(self, post_id, author, body, parent_id=None):
        async with self._sessions() as session, session.begin():
            if await session.get(Post, post_id) is None:
                raise PostNotFoundError("Post not found")
            if parent_id is not None:
                await self._ensure_repliable(session, post_id, parent_id)
            comment = Comment(post_id=post_id, parent_id=parent_id, author=author, body=body)
            session.add(comment)
            await session.flush()
            await session.refresh(comment)
            return _as_dict(comment)

    @staticmethod
    async def _ensure_repliable(session: AsyncSession, post_id: int, parent_id: int) -> None:
        parent = await session.get(Comment, parent_id)
        if parent is None or parent.post_id != post_id:
            raise CommentNotFoundError("Parent comment not found")
        if parent.parent_id is not None:
            raise NestingDepthError("Cannot reply to a reply (max 1-depth nesting)")

    # -- Thumbs (posts only) -------------------------------------------------

    async def toggle_thumb(self, post_id, voter, direction):
        async with self._sessions() as session, session.begin():
            # Locks the post so concurrent votes recount one after another.
            post = await session.scalar(select(Post).where(Post.id == post_id).with_for_update())
            if post is None:
                raise PostNotFoundError("Post not found")
            thumb = await session.scalar(select(Thumb).where(Thumb.post_id == post_id, Thumb.voter == voter))
            if thumb is None:
                session.add(Thumb(post_id=post_id, voter=voter, direction=direction))
            elif thumb.direction == direction:
                await session.delete(thumb)
            else:
                thumb.direction = direction
            await session.flush()

            up, down = (await session.execute(_thumb_counts(post_id))).one()
            post.thumbs_up, post.thumbs_down = up, down
            return {"thumbs_up": up, "thumbs_down": down}


def _thumb_counts(post_id: int):
    def votes(direction: int):
        return func.coalesce(func.sum(case((Thumb.direction == direction, 1), else_=0)), 0)

    return select(votes(1), votes(-1)).where(Thumb.post_id == post_id)
