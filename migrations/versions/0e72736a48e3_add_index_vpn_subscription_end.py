"""add_index_vpn_subscription_end

Revision ID: 0e72736a48e3
Revises: 9d7c22fdde04
Create Date: 2026-06-30 11:13:06.712940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0e72736a48e3'
down_revision: Union[str, Sequence[str], None] = '9d7c22fdde04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Создаём индекс для ускорения запросов по истечению подписок
    op.create_index('ix_bot_users_vpn_subscription_end', 'bot_users', ['vpn_subscription_end'])

def downgrade() -> None:
    # Удаляем индекс при откате
    op.drop_index('ix_bot_users_vpn_subscription_end', table_name='bot_users')