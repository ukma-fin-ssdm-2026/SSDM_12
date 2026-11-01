"""Міграції запускаються окремо від API з owner-URL у змінній середовища."""

import os

from alembic import context
from sqlalchemy import create_engine

from api.infrastructure.tables import metadata

engine = create_engine(
    context.config.attributes.get("owner_url") or os.environ["UNISLOT_ADMIN_DATABASE_URL"],
    hide_parameters=True,
)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
