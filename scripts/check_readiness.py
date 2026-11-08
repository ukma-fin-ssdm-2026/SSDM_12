"""Перевіряє готовність PostgreSQL без запису даних і виводу облікових даних."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from random import SystemRandom

from psycopg import AsyncConnection, OperationalError, ProgrammingError
from psycopg.conninfo import make_conninfo
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from scripts.manage_db import load_environment

ATTEMPT_TIMEOUT_SECONDS = 1.0
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 0.1
MAX_BACKOFF_SECONDS = 0.25
_random = SystemRandom()


async def _select_one(conninfo: str) -> None:
    async with await AsyncConnection.connect(conninfo, autocommit=True) as connection:
        await connection.execute("SELECT 1")


async def check_postgres(conninfo: str) -> tuple[bool, int]:
    """Повертає стан залежності та кількість виконаних спроб."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with asyncio.timeout(ATTEMPT_TIMEOUT_SECONDS):
                await _select_one(conninfo)
        except (OperationalError, TimeoutError):
            if attempt < MAX_ATTEMPTS:
                ceiling = min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2 ** (attempt - 1))
                await asyncio.sleep(_random.uniform(0.0, ceiling))
        else:
            return True, attempt
    return False, MAX_ATTEMPTS


def _postgres_conninfo() -> str:
    url = make_url(os.environ.get("UNISLOT_DATABASE_URL", ""))
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("expected a PostgreSQL URL")
    _, options = PGDialect_psycopg().create_connect_args(url)
    return make_conninfo(**options)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, help="Файл середовища в корені або підпапці проєкту"
    )
    args = parser.parse_args(argv)

    try:
        load_environment(args.env_file)
        conninfo = _postgres_conninfo()
    except (ArgumentError, OSError, ProgrammingError, ValueError):
        print(json.dumps({"status": "misconfigured", "dependency": "postgresql"}))
        return 2

    # psycopg потребує SelectorEventLoop у Windows.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        healthy, attempts = runner.run(check_postgres(conninfo))
    status = "healthy" if healthy else "unhealthy"
    print(json.dumps({"status": status, "dependency": "postgresql", "attempts": attempts}))
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
