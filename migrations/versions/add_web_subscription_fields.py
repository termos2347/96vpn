"""Add web subscription fields to users table

Revision ID: add_web_subscription_fields
Revises: f5c7a3e86735_add_last_reminder_sent_to_users
Create Date: 2024-04-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_web_subscription_fields'
down_revision = 'f5c7a3e86735_add_last_reminder_sent_to_users'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем новые поля
    op.add_column('users', sa.Column('email', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('hashed_password', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('source', sa.String(20), nullable=False, server_default='bot'))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('expiry_date', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('yookassa_payment_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('yookassa_customer_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('payment_method_id', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    
    # Делаем user_id допускающим NULL
    op.alter_column('users', 'user_id', existing_type=sa.BigInteger(), nullable=True)
    
    # Создаём индексы
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_unique_constraint('uq_users_email', 'users', ['email'])


def downgrade() -> None:
    # Удаляем индексы и констрейнты
    op.drop_constraint('uq_users_email', 'users', type_='unique')
    op.drop_index('ix_users_email', table_name='users')
    
    # Удаляем колонки
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'created_at')
    op.drop_column('users', 'payment_method_id')
    op.drop_column('users', 'yookassa_customer_id')
    op.drop_column('users', 'yookassa_payment_id')
    op.drop_column('users', 'expiry_date')
    op.drop_column('users', 'is_active')
    op.drop_column('users', 'source')
    op.drop_column('users', 'hashed_password')
    op.drop_column('users', 'email')
    
    # Возвращаем user_id в NOT NULL
    op.alter_column('users', 'user_id', existing_type=sa.BigInteger(), nullable=False)
