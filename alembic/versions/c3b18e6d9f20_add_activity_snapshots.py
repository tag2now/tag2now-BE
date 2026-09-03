"""add activity snapshots

Revision ID: c3b18e6d9f20
Revises: 8f21c7d3a4b0
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3b18e6d9f20"
down_revision: Union[str, Sequence[str], None] = "8f21c7d3a4b0"
branch_labels = None
depends_on = None

def upgrade() -> None:
	op.create_table("activity_snapshots", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
		sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False), sa.Column("total_players", sa.Integer(), nullable=False),
		sa.Column("total_rooms", sa.Integer(), nullable=False), sa.Column("rank_players", sa.Integer(), nullable=False), sa.Column("rank_rooms", sa.Integer(), nullable=False))
	op.create_index(op.f("ix_activity_snapshots_sampled_at"), "activity_snapshots", ["sampled_at"])

def downgrade() -> None:
	op.drop_index(op.f("ix_activity_snapshots_sampled_at"), table_name="activity_snapshots")
	op.drop_table("activity_snapshots")
