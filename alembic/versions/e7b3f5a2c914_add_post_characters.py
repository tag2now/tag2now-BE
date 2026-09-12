"""Split character tags out of post_type into a two-slot characters array."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e7b3f5a2c914"
down_revision = "d4a62e91f803"
branch_labels = None
depends_on = None

BOARD_TYPES = "('자유', '건의', '공략')"


def upgrade() -> None:
    op.add_column("posts", sa.Column("characters", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")))
    op.create_check_constraint("posts_characters_check", "posts", "cardinality(characters) <= 2")
    op.create_index("idx_posts_characters", "posts", ["characters"], postgresql_using="gin")
    # A character post_type was a character guide; it keeps that meaning as 공략.
    op.execute(f"UPDATE posts SET characters = ARRAY[post_type], post_type = '공략' WHERE post_type NOT IN {BOARD_TYPES}")


def downgrade() -> None:
    # Lossy: the old schema holds one character, so the second tag is dropped.
    op.execute("UPDATE posts SET post_type = characters[1] WHERE cardinality(characters) > 0")
    op.drop_index("idx_posts_characters", table_name="posts")
    op.drop_constraint("posts_characters_check", "posts", type_="check")
    op.drop_column("posts", "characters")
