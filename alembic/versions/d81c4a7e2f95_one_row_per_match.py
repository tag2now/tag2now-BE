"""Store a match as one row with a side per player, rebuilt from the events by queueing them again."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d81c4a7e2f95"
down_revision = "a3f9d2c6e481"
branch_labels = None
depends_on = None

# The consumer rebuilds every match from the events; events and room snapshots are never deleted.
_REQUEUE = "UPDATE match_events SET status = 'pending', attempts = 0, last_error = NULL, available_at = now()"


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("room_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("p1_npid", sa.Text(), nullable=False),
        sa.Column("p2_npid", sa.Text(), nullable=True),
        sa.Column("winner", sa.SmallInteger(), nullable=False),
        sa.Column("p1_event_id", sa.BigInteger(), nullable=True),
        sa.Column("p2_event_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("p1_event_id", name="uq_matches_p1_event"),
        sa.UniqueConstraint("p2_event_id", name="uq_matches_p2_event"),
        sa.ForeignKeyConstraint(["p1_event_id"], ["match_events.id"], name="fk_matches_p1_event"),
        sa.ForeignKeyConstraint(["p2_event_id"], ["match_events.id"], name="fk_matches_p2_event"),
        sa.CheckConstraint("winner IN (1, 2)", name="matches_winner_check"),
        sa.CheckConstraint("p1_event_id IS NOT NULL OR p2_event_id IS NOT NULL", name="matches_seen_check"),
        sa.CheckConstraint("(room_snapshot_id IS NULL) = (p2_npid IS NULL)", name="matches_room_check"),
    )
    op.create_index("idx_matches_p1", "matches", ["p1_npid", sa.text("id DESC")])
    op.create_index("idx_matches_p2", "matches", ["p2_npid", sa.text("id DESC")])
    op.create_index("idx_matches_room", "matches", ["room_snapshot_id"])
    op.create_index("idx_matches_played_at", "matches", ["played_at"])
    op.drop_table("match_results")
    op.execute(_REQUEUE)


def downgrade() -> None:
    op.create_table(
        "match_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("npid", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("chars", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("ranks", postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opponent_npid", sa.Text(), nullable=True),
        sa.Column("room_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("counterpart_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_match_results_event"),
        sa.ForeignKeyConstraint(["event_id"], ["match_events.id"], name="fk_match_results_event"),
        sa.ForeignKeyConstraint(["counterpart_id"], ["match_results.id"], name="fk_match_results_counterpart"),
    )
    op.create_index("idx_match_results_player", "match_results", ["npid", sa.text("played_at DESC")])
    op.create_index("idx_match_results_opponent", "match_results", ["opponent_npid"])
    op.create_index("idx_match_results_room", "match_results", ["room_snapshot_id"])
    op.drop_table("matches")
    op.execute(_REQUEUE)
