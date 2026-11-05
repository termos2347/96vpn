"""init_squashed

Revision ID: ad6e3877263b
Revises:
Create Date: 2026-07-11 15:40:54.546825

Пустая ревизия-заглушка. Исторически содержала drop_index для таблиц,
которые ещё не созданы (создаются в 1b847c7aa315), из-за чего
`alembic upgrade head` падал на чистой БД. Оставлена как no-op,
чтобы не ломать уже существующие цепочки alembic_version.
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'ad6e3877263b'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
