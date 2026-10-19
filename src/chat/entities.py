"""SQLAlchemy ORM entities for chat persistence."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Identity, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("length(body) <= 200", name="chat_messages_body_check"),
        Index("idx_chat_messages_created_at", "created_at"),
    )
    # The sequence outlives the process, so an id is never handed out twice.
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    author_username: Mapped[str] = mapped_column(Text, nullable=False)
    author_online_name: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # The service's clock, not now(): the play-day window is computed from the same clock.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    author_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
