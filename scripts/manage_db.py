"""Міграції, явне наповнення демо-даними й ізольований local-init; секрети не друкує."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def load_environment(path: Path | None) -> None:
    if path:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.startswith("UNISLOT_"):
                    os.environ[key] = value


def migrate(owner_url: str, role: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    # env.py reads these attributes, without writing credentials into the INI.
    config.attributes["owner_url"] = owner_url
    config.attributes["app_role"] = role
    command.upgrade(config, "head")


def seed_demo(url: str) -> bool:
    from api.infrastructure.codec import COLLECTIONS
    from api.infrastructure.postgres import PostgresStore
    from api.stubs.store import StubStore

    backend = PostgresStore(url)
    try:
        with backend.lock:
            if backend.users:
                return False
            demo = StubStore()
            demo.reset()
            for name in COLLECTIONS:
                setattr(backend, name, copy.deepcopy(getattr(demo, name)))
        return True
    finally:
        backend.close()


def main() -> None:
    from scripts.postgres_dev import LocalCluster

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("local-init", "stop-local", "migrate", "seed-demo"))
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    load_environment(args.env_file)
    if args.action in ("local-init", "stop-local"):
        cluster = LocalCluster(ROOT / "pgdata/dev", port=55436)
        if args.action == "stop-local":
            cluster.started = True
            cluster.stop()
            print("Isolated local PostgreSQL stopped")
            return
        cluster.start()
        envfile = ROOT / ".env.local"
        if envfile.exists():
            lines = envfile.read_text(encoding="utf-8").splitlines()
            owner_lines = [
                line
                for line in lines
                if line.startswith(("UNISLOT_ADMIN_DATABASE_URL=", "UNISLOT_APP_ROLE="))
            ]
            if owner_lines:
                (ROOT / ".env.migrations.local").write_text(
                    "\n".join(owner_lines) + "\n", encoding="utf-8"
                )
                envfile.write_text(
                    "\n".join(line for line in lines if line not in owner_lines) + "\n",
                    encoding="utf-8",
                )
            if not any(line.startswith("UNISLOT_SESSION_COOKIE_SECURE=") for line in lines):
                with envfile.open("a", encoding="utf-8") as output:
                    output.write("UNISLOT_SESSION_COOKIE_SECURE=0\n")
            print("Isolated cluster running; existing .env.local preserved")
            return
        role = "unislot_app"
        owner_url, app_url = cluster.create_database("unislot_local", role)
        migrate(owner_url, role)
        seed_demo(app_url)
        envfile.write_text(
            f"UNISLOT_DATABASE_URL={app_url}\nUNISLOT_DEMO_AUTH=1\nUNISLOT_EXPORT_OPENAPI=0\nUNISLOT_SESSION_COOKIE_SECURE=0\n",
            encoding="utf-8",
        )
        (ROOT / ".env.migrations.local").write_text(
            f"UNISLOT_ADMIN_DATABASE_URL={owner_url}\nUNISLOT_APP_ROLE={role}\n", encoding="utf-8"
        )
        print("Isolated database ready; credentials saved in ignored .env.local")
    elif args.action == "migrate":
        migrate(os.environ["UNISLOT_ADMIN_DATABASE_URL"], os.environ["UNISLOT_APP_ROLE"])
        print("Migrations applied")
    else:
        print(
            "Demo inserted"
            if seed_demo(os.environ["UNISLOT_DATABASE_URL"])
            else "Existing data preserved"
        )


if __name__ == "__main__":
    main()
