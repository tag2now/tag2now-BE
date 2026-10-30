"""Add stream_channels: an RPCN account's channel on a streaming platform."""

from alembic import op
import sqlalchemy as sa

revision = "e3557af59234"
down_revision = "4a584ecc1275"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stream_channels",
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("channel_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("username", "platform"),
        sa.UniqueConstraint("platform", "channel_id", name="uq_stream_channels_channel"),
    )


def downgrade() -> None:
    op.drop_table("stream_channels")
