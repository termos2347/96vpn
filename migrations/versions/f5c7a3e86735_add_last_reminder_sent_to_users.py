"""add last_reminder_sent to users

Revision ID: f5c7a3e86735
Revises: e588323591d9
Create Date: 2026-04-25 15:14:23.476339

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5c7a3e86735'
down_revision: Union[str, Sequence[str], None] = 'e588323591d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
