"""SQLAlchemy ORM adapter for the community repository."""
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from community.entities import Comment, Post, Thumb
from community.exceptions import CommentNotFoundError, NestingDepthError, OwnershipError, PostNotFoundError
from community.ports import CommunityRepository
from shared.database import get_session_factory

def _dict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}

class PostgresCommunityRepository(CommunityRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None): self._sessions = session_factory
    async def init(self): self._sessions = self._sessions or get_session_factory()
    async def close(self): pass
    @property
    def sessions(self):
        if self._sessions is None: raise RuntimeError("Community repository not initialized")
        return self._sessions
    async def list_posts(self, page, page_size, post_type=None):
        async with self.sessions() as s:
            count = func.count(Comment.id).label("comment_count")
            q = select(Post, count).outerjoin(Comment, Comment.post_id == Post.id).group_by(Post.id)
            if post_type: q = q.where(Post.post_type == post_type)
            total = await s.scalar(select(func.count()).select_from(Post).where(Post.post_type == post_type) if post_type else select(func.count()).select_from(Post))
            rows = (await s.execute(q.order_by(Post.created_at.desc()).limit(page_size).offset((page-1)*page_size))).all()
            return [{**_dict(p), "comment_count": c} for p,c in rows], total
    async def get_post(self, post_id):
        async with self.sessions() as s:
            row = await s.get(Post, post_id)
            if row is None: raise PostNotFoundError("Post not found")
            return _dict(row)
    async def get_post_comments(self, post_id):
        async with self.sessions() as s:
            return [_dict(x) for x in (await s.scalars(select(Comment).where(Comment.post_id==post_id).order_by(Comment.created_at))).all()]
    async def create_post(self, author, title, body, post_type="자유"):
        async with self.sessions() as s, s.begin():
            row=Post(author=author,title=title,body=body,post_type=post_type); s.add(row); await s.flush(); await s.refresh(row); return _dict(row)
    async def delete_post(self, post_id, user):
        async with self.sessions() as s, s.begin():
            row=await s.get(Post,post_id)
            if row is None: raise PostNotFoundError("Post not found")
            if row.author != user: raise OwnershipError("Not your post")
            await s.delete(row)
    async def create_comment(self, post_id, author, body, parent_id=None):
        async with self.sessions() as s, s.begin():
            if await s.get(Post,post_id) is None: raise PostNotFoundError("Post not found")
            if parent_id is not None:
                parent=await s.get(Comment,parent_id)
                if parent is None or parent.post_id != post_id: raise CommentNotFoundError("Parent comment not found")
                if parent.parent_id is not None: raise NestingDepthError("Cannot reply to a reply (max 1-depth nesting)")
            row=Comment(post_id=post_id,parent_id=parent_id,author=author,body=body); s.add(row); await s.flush(); await s.refresh(row); return _dict(row)
    async def toggle_thumb(self, post_id, voter, direction):
        async with self.sessions() as s, s.begin():
            post=await s.scalar(select(Post).where(Post.id==post_id).with_for_update())
            if post is None: raise PostNotFoundError("Post not found")
            thumb=await s.scalar(select(Thumb).where(Thumb.post_id==post_id,Thumb.voter==voter))
            if thumb and thumb.direction == direction: await s.delete(thumb)
            elif thumb: thumb.direction=direction
            else: s.add(Thumb(post_id=post_id,voter=voter,direction=direction))
            await s.flush()
            up,down=(await s.execute(select(func.coalesce(func.sum(case((Thumb.direction==1,1),else_=0)),0),func.coalesce(func.sum(case((Thumb.direction==-1,1),else_=0)),0)).where(Thumb.post_id==post_id))).one()
            post.thumbs_up,post.thumbs_down=up,down
            return {"thumbs_up":up,"thumbs_down":down}
