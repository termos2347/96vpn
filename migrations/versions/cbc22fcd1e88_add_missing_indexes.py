"""add_missing_indexes

Revision ID: <авто-генерируется>
Revises: 575c94820dfd
Create Date: 2026-06-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'ваш_ревизионный_ид'
down_revision = '575c94820dfd'
branch_labels = None
depends_on = None

def upgrade():
    # Восстанавливаем индекс на vpn_subscription_end (был удалён)
    op.create_index('ix_bot_users_vpn_subscription_end', 'bot_users', ['vpn_subscription_end'])
    # Добавляем индекс на vpn_client_id
    op.create_index('ix_bot_users_vpn_client_id', 'bot_users', ['vpn_client_id'])

def downgrade():
    op.drop_index('ix_bot_users_vpn_client_id', table_name='bot_users')
    op.drop_index('ix_bot_users_vpn_subscription_end', table_name='bot_users')