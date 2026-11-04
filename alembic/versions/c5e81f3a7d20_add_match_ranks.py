"""Add each character's rank going into a match, to queued events and stored results."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c5e81f3a7d20"
down_revision = "b2d7e4a91c35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: matches recorded before this have no ranks to give.
    op.add_column("match_events", sa.Column("ranks", postgresql.ARRAY(sa.Integer()), nullable=True))
    op.add_column("match_results", sa.Column("ranks", postgresql.ARRAY(sa.Integer()), nullable=True))


def downgrade() -> None:
    op.drop_column("match_results", "ranks")
    op.drop_column("match_events", "ranks")
