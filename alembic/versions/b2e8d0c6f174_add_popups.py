"""Add popups: messages admins show visitors on opening the site."""

from alembic import op
import sqlalchemy as sa

revision = "b2e8d0c6f174"
down_revision = "d81c4a7e2f95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "popups",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("image_type", sa.Text(), nullable=True),
        sa.Column("image_hash", sa.Text(), nullable=True),
        sa.Column("allow_dismiss_forever", sa.Boolean(), nullable=False),
        sa.Column("allow_dismiss_day", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("popups")
