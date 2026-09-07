"""drop the reservation duration nobody could predict

Revision ID: b5e93c17d240
Revises: a7f4c21b9e83
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b5e93c17d240"
down_revision: Union[str, Sequence[str], None] = "a7f4c21b9e83"
branch_labels = None
depends_on = None

_DEFAULT_MINUTES = 60


def upgrade() -> None:
	# Hosts were asked how long they expected to play, and the estimate decided
	# when a reservation expired. The guess was never reliable, so expiry is now
	# a fixed hour past the start and the column has no reader left.
	op.drop_column("reservations", "duration_minutes")


def downgrade() -> None:
	# The original estimates are gone; every restored row gets the hour that
	# replaced them, which is what the expiry rule now assumes anyway.
	op.add_column("reservations", sa.Column("duration_minutes", sa.Integer(), nullable=True))
	op.execute(f"UPDATE reservations SET duration_minutes = {_DEFAULT_MINUTES}")
	op.alter_column("reservations", "duration_minutes", nullable=False)
