"""create_users_table

Revision ID: e0c873676bc3
Revises: f5c7a3e86735
Create Date: 2026-04-26 09:09:08.848863

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0c873676bc3'
down_revision: Union[str, Sequence[str], None] = 'f5c7a3e86735'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False, unique=True, index=True),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('vpn_subscription_end', sa.DateTime(), nullable=True),
        sa.Column('bypass_subscription_end', sa.DateTime(), nullable=True),
        sa.Column('vpn_client_id', sa.String(length=255), nullable=True),
        sa.Column('last_reminder_sent', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('users')
