"""Операторський CLI outbox: список failed і явний аудитований повтор одного ID."""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> int:
    """Працює лише з restricted runtime URL; не друкує адрес, payload чи DSN."""
    from sqlalchemy.exc import DBAPIError

    from api import clock
    from api.infrastructure.notification_ops import RetryRejected, failed_messages, retry_failed
    from api.infrastructure.postgres import PostgresStore
    from scripts.manage_db import load_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    listing = commands.add_parser("failed")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    retry = commands.add_parser("retry")
    retry.add_argument("notification_id", type=uuid.UUID)
    retry.add_argument("--actor-id", type=uuid.UUID, required=True)
    retry.add_argument("--reason", required=True)
    args = parser.parse_args()
    load_environment(args.env_file)
    backend = None
    try:
        backend = PostgresStore(os.environ["UNISLOT_DATABASE_URL"])
        if args.action == "failed":
            result = {
                "items": failed_messages(backend.engine, limit=args.limit, offset=args.offset)
            }
        else:
            result = {
                "status": retry_failed(
                    backend.engine,
                    args.notification_id,
                    args.actor_id,
                    args.reason,
                    clock.utc_now(),
                )
            }
        print(json.dumps(result, default=str, ensure_ascii=False))
        return 0
    except RetryRejected as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (DBAPIError, KeyError, ValueError):
        print(json.dumps({"error": "configuration_or_database_unavailable"}))
        return 1
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
