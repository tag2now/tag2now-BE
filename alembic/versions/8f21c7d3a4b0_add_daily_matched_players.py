"""add daily matched players

Revision ID: 8f21c7d3a4b0
Revises: 3d058284bcba
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f21c7d3a4b0"
down_revision: Union[str, Sequence[str], None] = "3d058284bcba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
	op.create_table(
		"daily_matched_players",
		sa.Column("date", sa.Date(), nullable=False),
		sa.Column("npid", sa.String(), nullable=False),
		sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
		sa.PrimaryKeyConstraint("date", "npid"),
	)
	op.execute("""
		INSERT INTO daily_matched_players (date, npid, first_seen_at)
		SELECT
			(created_dt AT TIME ZONE 'Asia/Seoul')::date,
			npid,
			MIN(created_dt)
		FROM (
			SELECT created_dt, user1_npid AS npid FROM rank_match_snapshots
			UNION ALL
			SELECT created_dt, user2_npid AS npid FROM rank_match_snapshots
		) participants
		WHERE npid <> ''
		GROUP BY (created_dt AT TIME ZONE 'Asia/Seoul')::date, npid
		ON CONFLICT (date, npid) DO NOTHING
	""")


def downgrade() -> None:
	op.drop_table("daily_matched_players")
