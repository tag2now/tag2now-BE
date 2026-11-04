"""Add match records: saves compared per player, a queue of finished matches, and who played whom."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2d7e4a91c35"
down_revision = "9c1d4e7a2b56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The default keeps the old image's inserts working between this and its replacement.
    op.add_column(
        "rank_match_snapshots",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("UPDATE rank_match_snapshots SET last_seen_at = created_dt")

    op.create_table(
        "save_states",
        sa.Column("npid", sa.Text(), nullable=False),
        sa.Column("data_id", sa.BigInteger(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("chars", postgresql.JSONB(), nullable=False),
        sa.Column("start_chars", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("merged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("npid"),
    )

    op.create_table(
        "match_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("npid", sa.Text(), nullable=False),
        sa.Column("data_id", sa.BigInteger(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("chars", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("npid", "data_id", name="uq_match_events_save"),
        sa.CheckConstraint("result IN ('win', 'loss')", name="match_events_result_check"),
        sa.CheckConstraint("status IN ('pending', 'done', 'dead')", name="match_events_status_check"),
    )
    op.create_index("idx_match_events_pending", "match_events", ["id"], postgresql_where=sa.text("status = 'pending'"))

    op.create_table(
        "match_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("npid", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("chars", postgresql.ARRAY(sa.Integer()), nullable=False),
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


def downgrade() -> None:
    op.drop_table("match_results")
    op.drop_table("match_events")
    op.drop_table("save_states")
    op.drop_column("rank_match_snapshots", "last_seen_at")
