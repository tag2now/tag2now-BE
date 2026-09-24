"""reservation owners are accounts

Ownership moves from anonymous capability tokens to the RPCN username of the
signed-in user. The token hashes are dropped rather than kept: no route accepts
a token any more, so rows written before this revision simply have no owner.
They are short-lived --- nothing is listed past the next 06:00 KST --- so that
costs at most one night's reservations their edit and cancel buttons.

Revision ID: f2c6a9d41e57
Revises: e7b3f5a2c914
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2c6a9d41e57"
down_revision: Union[str, Sequence[str], None] = "e7b3f5a2c914"
branch_labels = None
depends_on = None


def upgrade() -> None:
	op.add_column("reservation_comments", sa.Column("author_subject", sa.Text(), nullable=True))
	op.drop_column("reservation_comments", "author_token_hash")
	# Dropping the column takes its (reservation_id, participant_token_hash)
	# unique constraint with it.
	op.drop_column("reservation_participants", "participant_token_hash")
	op.drop_column("reservations", "host_token_hash")
	op.create_index(
		"uq_reservation_participants_active_subject", "reservation_participants", ["reservation_id", "subject"],
		unique=True, postgresql_where=sa.text("cancelled_at IS NULL AND subject IS NOT NULL"),
	)


def downgrade() -> None:
	# The hashes are gone; the empty string restores the columns' shape, and no
	# token hashes to it, so every row comes back ownerless as it went.
	op.drop_index("uq_reservation_participants_active_subject", table_name="reservation_participants")
	op.add_column("reservations", sa.Column("host_token_hash", sa.Text(), nullable=False, server_default=""))
	op.add_column("reservation_participants", sa.Column("participant_token_hash", sa.Text(), nullable=False, server_default=""))
	op.add_column("reservation_comments", sa.Column("author_token_hash", sa.Text(), nullable=False, server_default=""))
	op.drop_column("reservation_comments", "author_subject")
