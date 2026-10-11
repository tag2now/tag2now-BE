"""SQLAlchemy ORM entities for the streaming module."""

from datetime import datetime

from sqlalchemy import DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class StreamChannelRow(Base):
    """An RPCN account's channel on a streaming platform."""
    __tablename__ = "stream_channels"
    # One channel belongs to one account, so a LIVE mark never sits beside two players.
    __table_args__ = (UniqueConstraint("platform", "channel_id", name="uq_stream_channels_channel"),)

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    # As the platform named it at registration; only ever displayed.
    channel_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
