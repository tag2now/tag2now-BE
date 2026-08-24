"""baseline schema

Revision ID: 3d058284bcba
Revises: 
Create Date: 2026-08-24 14:29:40.896604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d058284bcba'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the schema formerly provisioned by application startup."""
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("post_type", sa.Text(), nullable=False, server_default=sa.text("'자유'")),
        sa.Column("thumbs_up", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("thumbs_down", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("length(title) <= 100", name="posts_title_check"),
        sa.CheckConstraint("length(body) <= 1000", name="posts_body_check"),
    )
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("comments.id", ondelete="CASCADE")),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("length(body) <= 1000", name="comments_body_check"),
    )
    op.create_index("idx_comments_post", "comments", ["post_id"])
    op.create_index("idx_comments_parent", "comments", ["parent_id"])
    op.create_table(
        "thumbs",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("voter", sa.Text(), nullable=False),
        sa.Column("direction", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("direction IN (1, -1)", name="thumbs_direction_check"),
        sa.UniqueConstraint("post_id", "voter"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("host_display_name", sa.Text(), nullable=False),
        sa.Column("host_subject", sa.Text()),
        sa.Column("host_ranks", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("host_token_hash", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_reservations_start_at", "reservations", ["start_at"])
    op.create_table(
        "reservation_participants",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), primary_key=True),
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("ranks", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("participant_token_hash", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("reservation_id", "participant_token_hash"),
    )
    op.create_index("idx_reservation_participants_active", "reservation_participants", ["reservation_id"], postgresql_where=sa.text("cancelled_at IS NULL"))
    op.create_table(
        "rank_match_snapshots",
        sa.Column("room_id", sa.Integer(), primary_key=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rank_id", sa.Integer(), nullable=False),
        sa.Column("user1_npid", sa.String(), nullable=False),
        sa.Column("user1_online_name", sa.String(), nullable=False),
        sa.Column("user2_npid", sa.String(), nullable=False),
        sa.Column("user2_online_name", sa.String(), nullable=False),
    )
    op.create_index(op.f("ix_rank_match_snapshots_created_dt"), "rank_match_snapshots", ["created_dt"])
    op.create_index(op.f("ix_rank_match_snapshots_user1_npid"), "rank_match_snapshots", ["user1_npid"])
    op.create_index(op.f("ix_rank_match_snapshots_user2_npid"), "rank_match_snapshots", ["user2_npid"])
    op.create_table(
        "hourly_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hour_key", sa.String(), nullable=False),
        sa.Column("total_players", sa.Integer(), nullable=False),
        sa.Column("total_rooms", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_hourly_stats_hour_key"), "hourly_stats", ["hour_key"], unique=True)


def downgrade() -> None:
    """Drop the baseline schema in reverse dependency order."""
    op.drop_index(op.f("ix_hourly_stats_hour_key"), table_name="hourly_stats")
    op.drop_table("hourly_stats")
    op.drop_index(op.f("ix_rank_match_snapshots_user2_npid"), table_name="rank_match_snapshots")
    op.drop_index(op.f("ix_rank_match_snapshots_user1_npid"), table_name="rank_match_snapshots")
    op.drop_index(op.f("ix_rank_match_snapshots_created_dt"), table_name="rank_match_snapshots")
    op.drop_table("rank_match_snapshots")
    op.drop_index("idx_reservation_participants_active", table_name="reservation_participants")
    op.drop_table("reservation_participants")
    op.drop_index("idx_reservations_start_at", table_name="reservations")
    op.drop_table("reservations")
    op.drop_table("thumbs")
    op.drop_index("idx_comments_parent", table_name="comments")
    op.drop_index("idx_comments_post", table_name="comments")
    op.drop_table("comments")
    op.drop_table("posts")
