"""Lock/read context in one round trip; business validation stays in Python."""

import os
from pathlib import Path

from alembic import op

from api.infrastructure.security import grant_runtime

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade() -> None:
    """Adds only an invoker function and its explicit runtime EXECUTE grant."""
    conn = op.get_bind()
    conn.exec_driver_sql(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))
    grant_runtime(
        conn, op.get_context().config.attributes.get("app_role") or os.environ["UNISLOT_APP_ROLE"]
    )


def downgrade() -> None:
    """Migration rollback is an operator action rather than destructive downgrade."""
    raise RuntimeError("destructive downgrade is disabled")
