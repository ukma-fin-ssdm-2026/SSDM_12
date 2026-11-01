"""Окремий час повторної спроби без зміни початкового scheduled_for."""

from alembic import op
from sqlalchemy import Column, DateTime

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Додає окрему дату повтору без зміни первинного часу сповіщення."""
    op.add_column("notification", Column("next_attempt_at", DateTime(timezone=True)))


def downgrade() -> None:
    """Не видаляє робочі дані автоматично."""
    raise RuntimeError("destructive downgrade is intentionally unsupported; restore a backup")
