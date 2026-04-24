"""initial

Revision ID: e588323591d9
Revises: ebe392195874
Create Date: 2026-04-24 18:23:15.317694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e588323591d9'
down_revision: Union[str, Sequence[str], None] = 'ebe392195874'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
