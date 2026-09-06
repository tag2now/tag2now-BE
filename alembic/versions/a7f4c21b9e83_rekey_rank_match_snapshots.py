"""rekey rank match snapshots off the volatile RPCN room id

Revision ID: a7f4c21b9e83
Revises: c3b18e6d9f20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a7f4c21b9e83"
down_revision: Union[str, Sequence[str], None] = "c3b18e6d9f20"
branch_labels = None
depends_on = None

_UQ = "uq_rank_match_snapshots_match"


def upgrade() -> None:
	# room_id restarts at 1 whenever RPCN restarts, so it cannot be the key ---
	# colliding inserts were being dropped by ON CONFLICT DO NOTHING.
	op.drop_constraint("rank_match_snapshots_pkey", "rank_match_snapshots", type_="primary")
	op.alter_column("rank_match_snapshots", "room_id", type_=sa.BigInteger(), existing_nullable=False)
	op.execute("ALTER TABLE rank_match_snapshots ADD COLUMN id BIGSERIAL")
	op.create_primary_key("rank_match_snapshots_pkey", "rank_match_snapshots", ["id"])

	op.add_column("rank_match_snapshots", sa.Column("match_date", sa.Date(), nullable=True))
	op.execute("UPDATE rank_match_snapshots SET match_date = (created_dt AT TIME ZONE 'Asia/Seoul')::date")
	op.alter_column("rank_match_snapshots", "match_date", nullable=False)

	op.create_unique_constraint(_UQ, "rank_match_snapshots",
		["room_id", "user1_npid", "user2_npid", "match_date"])


def downgrade() -> None:
	op.drop_constraint(_UQ, "rank_match_snapshots", type_="unique")
	op.drop_column("rank_match_snapshots", "match_date")
	op.drop_constraint("rank_match_snapshots_pkey", "rank_match_snapshots", type_="primary")
	op.drop_column("rank_match_snapshots", "id")
	op.alter_column("rank_match_snapshots", "room_id", type_=sa.Integer(), existing_nullable=False)
	op.create_primary_key("rank_match_snapshots_pkey", "rank_match_snapshots", ["room_id"])
