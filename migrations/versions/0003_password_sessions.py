"""Облікові дані Argon2id, хешовані cookie-сесії та лічильник входів."""

import os
import secrets
from pathlib import Path

from alembic import op

from api.infrastructure.passwords import hash_password
from api.infrastructure.security import grant_runtime

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Створює лише нові таблиці; наявні користувачі не отримують демо-паролів."""
    conn = op.get_bind()
    # DDL contains a literal LIKE %, not a psycopg placeholder.
    ddl = Path(__file__).with_name("0003_schema.sql").read_text(encoding="utf-8")
    conn.exec_driver_sql(ddl.replace("%", "%%"))
    # Старим демо-записам не призначаємо відомий пароль: випадкове значення одразу
    # відкидається, у БД лишається тільки Argon2id. Доступ до demo-* окремо вимикається.
    conn.exec_driver_sql(
        "UPDATE app_user SET password_hash=%s, is_active=false WHERE password_hash IS NULL",
        (hash_password(secrets.token_urlsafe(32)),),
    )
    conn.exec_driver_sql("ALTER TABLE app_user ALTER COLUMN password_hash SET NOT NULL")
    grant_runtime(
        conn, op.get_context().config.attributes.get("app_role") or os.environ["UNISLOT_APP_ROLE"]
    )


def downgrade() -> None:
    """Сесії та облікові дані не видаляються автоматично."""
    raise RuntimeError("destructive downgrade is intentionally unsupported; restore a backup")
