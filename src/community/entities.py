"""SQLAlchemy ORM entities for the community domain."""

from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from shared.database import Base

class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    __table_args__ = (
        CheckConstraint("length(title) <= 100", name="posts_title_check"),
        CheckConstraint("length(body) <= 1000", name="posts_body_check"),
    )
    author: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="자유")
    thumbs_up: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    thumbs_down: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    __table_args__ = (
        CheckConstraint("length(body) <= 1000", name="comments_body_check"),
        Index("idx_comments_post", "post_id"),
        Index("idx_comments_parent", "parent_id"),
    )
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=True)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class Thumb(Base):
    __tablename__ = "thumbs"
    __table_args__ = (
        CheckConstraint("direction IN (1, -1)", name="thumbs_direction_check"),
        UniqueConstraint("post_id", "voter"),
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    voter: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
