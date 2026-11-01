"""Постійні дані, outbox і append-only аудит; реалізація інваріантів ADR-002/DD-08."""

import os
from pathlib import Path

from alembic import op

from api.infrastructure.security import grant_runtime, install_audit_protection

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Власник створює схему; API надалі використовує лише обмежену роль."""
    conn = op.get_bind()
    conn.exec_driver_sql(Path(__file__).with_name("0001_schema.sql").read_text(encoding="utf-8"))
    install_audit_protection(conn)
    grant_runtime(
        conn, op.get_context().config.attributes.get("app_role") or os.environ["UNISLOT_APP_ROLE"]
    )


def downgrade() -> None:
    """Не видаляє робочі дані та аудит автоматично."""
    raise RuntimeError("destructive downgrade is intentionally unsupported; restore a backup")
