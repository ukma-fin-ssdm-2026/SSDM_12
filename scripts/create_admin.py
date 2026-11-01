"""Одноразове створення першого реального admin: пароль лише через приховане введення."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> None:
    from pydantic import ValidationError

    from api import clock
    from api.infrastructure.postgres import PostgresStore
    from api.schemas.auth import RegisterIn
    from api.services.auth_service import bootstrap_admin
    from api.stubs.store import store
    from scripts.manage_db import load_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    args = parser.parse_args()
    load_environment(args.env_file)
    password = getpass.getpass("New administrator password (15-1024 characters): ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("passwords do not match")
    try:
        data = RegisterIn(full_name=args.full_name, email=args.email, password=password)
    except ValidationError:
        parser.error("valid email/name and a password of 15-1024 characters required")
    backend = PostgresStore(os.environ["UNISLOT_DATABASE_URL"])
    previous = store.set_backend(backend)
    try:
        bootstrap_admin(
            data.full_name, str(data.email), data.password.get_secret_value(), clock.utc_now()
        )
        print("Administrator initialized; sign in through /api/v1/auth/login")
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        store.set_backend(previous)
        backend.close()


if __name__ == "__main__":
    main()
