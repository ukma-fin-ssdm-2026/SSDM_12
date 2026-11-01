"""Окремий Worker outbox; не друкує повідомлень, URL чи контактних даних."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main() -> None:
    from sqlalchemy.exc import DBAPIError

    from api import clock
    from api.infrastructure.outbox import PostgresOutbox, dispatch_due
    from api.infrastructure.postgres import PostgresStore
    from api.services.worker_service import refresh_horizon
    from api.stubs.store import store
    from scripts.manage_db import load_environment
    from unislot.notifications.domain.model import RetryPolicy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--base-delay", type=int, default=5)
    parser.add_argument("--max-delay", type=int, default=3600)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument(
        "--horizon-interval",
        type=float,
        default=3600,
        help="Refresh weekly horizon on startup and every N seconds",
    )
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0 or not 1 <= args.batch_size <= 100:
        parser.error("positive interval and batch-size 1..100 required")
    if not math.isfinite(args.horizon_interval) or args.horizon_interval <= 0:
        parser.error("horizon-interval must be positive and finite")
    load_environment(args.env_file)
    try:
        policy = RetryPolicy(args.max_attempts, args.base_delay, args.max_delay, args.lease_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    backend = PostgresStore(os.environ["UNISLOT_DATABASE_URL"])
    repository = PostgresOutbox(backend.engine)
    previous = store.set_backend(backend)
    next_refresh = 0
    try:
        while True:
            try:
                if time.monotonic() >= next_refresh:
                    created = refresh_horizon(clock.utc_now())
                    print(
                        json.dumps({"event": "horizon_refresh", "created_slots": created}),
                        flush=True,
                    )
                    next_refresh = time.monotonic() + args.horizon_interval
                result = dispatch_due(
                    repository, clock.utc_now(), batch=args.batch_size, policy=policy
                )
                print(json.dumps(asdict(result)), flush=True)
            except DBAPIError:
                print(
                    json.dumps({"event": "worker_retry", "code": "database_unavailable"}),
                    flush=True,
                )
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        store.set_backend(previous)
        backend.close()


if __name__ == "__main__":
    main()
