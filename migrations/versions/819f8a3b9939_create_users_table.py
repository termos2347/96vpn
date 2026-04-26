"""create users table

Revision ID: 819f8a3b9939
Revises: e0c873676bc3
Create Date: 2026-04-26 09:11:09.332292

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '819f8a3b9939'
down_revision: Union[str, Sequence[str], None] = 'e0c873676bc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
