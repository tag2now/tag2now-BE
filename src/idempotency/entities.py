"""SQLAlchemy ORM entity for idempotency keys."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class IdempotencyKeyRow(Base):
    """One write a user asked for, and the answer it got.

    The unique key is what makes a retry safe: a second insert of the same key
    waits for the first transaction and then conflicts, so only one request runs.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("subject", "key", name="uq_idempotency_keys_subject_key"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    # Null only inside the claiming transaction; set before it commits.
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
