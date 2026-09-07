"""add reservation comments

Revision ID: c8a41f625b93
Revises: b5e93c17d240
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c8a41f625b93"
down_revision: Union[str, Sequence[str], None] = "b5e93c17d240"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.create_table(
		"reservation_comments",
		sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
		sa.Column("reservation_id", sa.Integer(), nullable=False),
		sa.Column("author", sa.Text(), nullable=False),
		sa.Column("body", sa.Text(), nullable=False),
		sa.Column("author_token_hash", sa.Text(), nullable=False),
		sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
		sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
		sa.CheckConstraint("length(body) <= 500", name="reservation_comments_body_check"),
		sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="CASCADE"),
	)
	# Every read is "the live comments on one reservation", so the partial index
	# carries the deleted_at filter rather than leaving it to a heap check.
	op.create_index(
		"idx_reservation_comments_active", "reservation_comments", ["reservation_id"],
		postgresql_where=sa.text("deleted_at IS NULL"),
	)


def downgrade() -> None:
	op.drop_index("idx_reservation_comments_active", table_name="reservation_comments")
	op.drop_table("reservation_comments")
