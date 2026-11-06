"""Add idempotency_keys: one row per creating request, so a retry replays its answer."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "58ba2058499e"
down_revision = "b2e8d0c6f174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", "key", name="uq_idempotency_keys_subject_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
