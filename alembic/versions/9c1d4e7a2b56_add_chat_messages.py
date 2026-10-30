"""Add chat_messages: lobby chat that survives a restart."""

from alembic import op
import sqlalchemy as sa

revision = "9c1d4e7a2b56"
down_revision = "e3557af59234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("author_username", sa.Text(), nullable=False),
        sa.Column("author_online_name", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("length(body) <= 200", name="chat_messages_body_check"),
    )
    op.create_index("idx_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_chat_messages_created_at", table_name="chat_messages")
    op.drop_table("chat_messages")
