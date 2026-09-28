"""Drop hourly_stats; hourly activity is read from activity_snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "4a584ecc1275"
down_revision = "f2c6a9d41e57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_hourly_stats_hour_key"), table_name="hourly_stats")
    op.drop_table("hourly_stats")


def downgrade() -> None:
    # Restores the table empty: its rows counted new matches, not players.
    op.create_table(
        "hourly_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("hour_key", sa.String(), nullable=False),
        sa.Column("total_players", sa.Integer(), nullable=False),
        sa.Column("total_rooms", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(op.f("ix_hourly_stats_hour_key"), "hourly_stats", ["hour_key"], unique=True)
