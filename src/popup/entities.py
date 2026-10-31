"""SQLAlchemy ORM entities for the popup module."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class PopupRow(Base):
    """A message admins show visitors when they open the site."""

    __tablename__ = "popups"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Deferred, so a list of popups does not read every image out of the database.
    image: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    image_type: Mapped[str | None] = mapped_column(Text)
    image_hash: Mapped[str | None] = mapped_column(Text)
    allow_dismiss_forever: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_dismiss_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
