"""Add optional YouTube video to community posts."""
from alembic import op
import sqlalchemy as sa

revision = "d4a62e91f803"
down_revision = "c8a41f625b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("youtube_video_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "youtube_video_id")
