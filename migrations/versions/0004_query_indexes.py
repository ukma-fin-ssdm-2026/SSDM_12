"""Індекси HTTP-пошуку й checkpoint фонового розширення горизонту."""

from alembic import context, op

from api.infrastructure.security import grant_runtime

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade() -> None:
    """Адитивна міграція; старі записи, сесії й історія не змінюються."""
    conn = op.get_bind()
    conn.exec_driver_sql(
        "CREATE TABLE maintenance_checkpoint (name text PRIMARY KEY, completed_at timestamptz NOT NULL)"
    )
    conn.exec_driver_sql(
        "CREATE INDEX ix_slot_active_order ON slot (starts_at, id) WHERE is_active"
    )
    conn.exec_driver_sql("CREATE INDEX ix_booking_student ON booking (student_id)")
    conn.exec_driver_sql("CREATE INDEX ix_block_resource ON time_block (resource_id, starts_at)")
    config = context.get_context().config
    import os

    grant_runtime(conn, config.attributes.get("app_role") or os.environ["UNISLOT_APP_ROLE"])


def downgrade() -> None:
    """Відновлення історії виконує оператор із backup, не destructive downgrade."""
    raise RuntimeError("destructive downgrade is disabled")
