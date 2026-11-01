"""Ізольовані HTTP-виміри на PostgreSQL; не використовує робочу БД або Docker."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import secrets
import shutil
import socket
import subprocess  # nosec B404 -- starts only the fixed local API with no shell
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import httpx2 as httpx  # noqa: E402
from sqlalchemy import create_engine, func, insert, select  # noqa: E402

from api.infrastructure import tables as t  # noqa: E402
from api.infrastructure.passwords import UNUSABLE_HASH  # noqa: E402
from api.infrastructure.postgres import POOL_SIZE  # noqa: E402
from api.services.auth_service import token_digest  # noqa: E402
from scripts.manage_db import migrate  # noqa: E402
from scripts.postgres_dev import LocalCluster  # noqa: E402


def seed_load(url: str) -> dict:
    """Рівно 200 користувачів і 5000 слотів; сесії існують тільки в пам'яті runner."""
    now = datetime.now(UTC)
    users = [uuid.uuid4() for _ in range(200)]
    resources = [uuid.uuid4() for _ in range(100)]
    slots = [uuid.uuid4() for _ in range(5000)]
    tokens = [(secrets.token_urlsafe(32), secrets.token_urlsafe(32)) for _ in users[:198]]
    policy = uuid.uuid4()
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                insert(t.users),
                [
                    {
                        "id": uid,
                        "full_name": f"Load student {i}",
                        "email": f"load-{i}@example.com",
                        "password_hash": UNUSABLE_HASH,
                        "is_active": True,
                        "created_at": now,
                    }
                    for i, uid in enumerate(users)
                ],
            )
            conn.execute(
                insert(t.roles),
                [
                    {
                        "user_id": uid,
                        "role": "student" if i < 198 else "provider" if i == 198 else "admin",
                    }
                    for i, uid in enumerate(users)
                ],
            )
            conn.execute(
                insert(t.resources),
                [
                    {
                        "id": rid,
                        "name": f"Load room {i}",
                        "type": "room",
                        "capacity": 30,
                        "provider_id": users[198],
                    }
                    for i, rid in enumerate(resources)
                ],
            )
            conn.execute(
                insert(t.policies).values(id=policy, booking_limit=3, cancel_window_minutes=120)
            )
            conn.execute(insert(t.current_policy).values(singleton=1, policy_id=policy))
            conn.execute(
                insert(t.slots),
                [
                    {
                        "id": sid,
                        "resource_id": resources[i % 100],
                        "starts_at": now + timedelta(days=2, minutes=(i // 100) * 30),
                        "ends_at": now + timedelta(days=2, minutes=(i // 100) * 30 + 30),
                        "is_active": True,
                    }
                    for i, sid in enumerate(slots)
                ],
            )
            conn.execute(
                insert(t.sessions),
                [
                    {
                        "id": uuid.uuid4(),
                        "token_hash": bytes.fromhex(token_digest(token)),
                        "csrf_hash": bytes.fromhex(token_digest(csrf)),
                        "user_id": uid,
                        "created_at": now,
                        "expires_at": now + timedelta(hours=2),
                    }
                    for uid, (token, csrf) in zip(users, tokens, strict=False)
                ],
            )
        return {"slots": slots, "tokens": tokens}
    finally:
        engine.dispose()


def measure(client: httpx.Client, jobs: list[dict], concurrency: int) -> dict:
    """Повні хвилі одночасних запитів; latency включає серверну чергу й читання тіла."""
    barrier = threading.Barrier(concurrency, timeout=120)

    def request(job):
        barrier.wait()
        started = time.perf_counter()
        try:
            response = client.request(**job)
            body = response.json()
            status, code = response.status_code, body.get("code")
            valid = (
                isinstance(body.get("items"), list) and len(body["items"]) == 20
                if job["method"] == "GET"
                else body.get("slot", {}).get("id") == job["json"]["slot_id"]
                if status == 201
                else code == "SLOT_ALREADY_BOOKED"
                if status == 409
                else False
            )
        except (httpx.HTTPError, ValueError):
            status, code = 0, "request_failed"
            valid = False
        return {
            "milliseconds": (time.perf_counter() - started) * 1000,
            "status": status,
            "code": code,
            "body_valid": valid,
        }

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        samples = list(pool.map(request, jobs))
    ordered = sorted(row["milliseconds"] for row in samples)
    return {
        "requests": len(samples),
        "concurrency": concurrency,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "p50_ms": round(ordered[math.ceil(len(ordered) * 0.50) - 1], 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "max_ms": round(ordered[-1], 3),
        "statuses": dict(Counter(str(r["status"]) for r in samples)),
        "codes": dict(Counter(r["code"] for r in samples if r["code"])),
        "invalid_bodies": sum(not r["body_valid"] for r in samples),
        "samples": samples,
    }


def run(output: Path, search_requests: int, api_workers: int = 1) -> dict:
    """Створює власний кластер, запускає API, зупиняє й видаляє лише власні дані."""
    output.mkdir(parents=True, exist_ok=True)
    directory = ROOT / "pgdata" / ("load-" + uuid.uuid4().hex)
    cluster = LocalCluster(directory)
    server = None
    try:
        cluster.start()
        owner_url, app_url = cluster.create_database("load_review", "load_app")
        migrate(owner_url, "load_app")
        data = seed_load(app_url)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH")
            if key in os.environ
        }
        env.update(
            {
                "PYTHONPATH": "src",
                "PYTHONIOENCODING": "utf-8",
                "UNISLOT_DATABASE_URL": app_url,
                "UNISLOT_DEMO_AUTH": "0",
                "UNISLOT_EXPORT_OPENAPI": "0",
                "UNISLOT_SESSION_COOKIE_SECURE": "0",
            }
        )
        with (output / "server.txt").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(  # noqa: S603 -- fixed local application, no shell
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "api.main:app",
                    "--app-dir",
                    "src",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                    "--workers",
                    str(api_workers),
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )  # nosec B603 -- fixed executable/module; port is an OS-assigned integer
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(
                base_url=base,
                trust_env=False,
                timeout=120,
                limits=httpx.Limits(max_connections=110, max_keepalive_connections=110),
            ) as client:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline or server.poll() is not None:
                        raise RuntimeError("isolated API did not become ready; see server.txt")
                    time.sleep(0.1)

                def headers(i):
                    token, csrf = data["tokens"][i % 198]
                    return {"Cookie": f"unislot_session={token}", "X-CSRF-Token": csrf}

                for _ in range(5):
                    if client.get("/api/v1/slots", headers=headers(0)).status_code != 200:
                        raise RuntimeError("search warmup failed; see server.txt")
                result = {
                    "created_at": datetime.now(UTC).isoformat(),
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "database": "PostgreSQL 16 (native isolated cluster)",
                    "deployment": "native Windows; Docker condition not verified",
                    "slots": 5000,
                    "users": 200,
                    "booking_warmups": 10,
                    "client": "httpx2 sync; synchronized thread waves; full response body",
                    "percentile": "nearest rank",
                    "api_worker_threads": 40,
                    "api_processes": api_workers,
                    "database_pool_per_process": POOL_SIZE,
                }
                scenarios = [
                    (
                        "search",
                        [
                            {"method": "GET", "url": "/api/v1/slots", "headers": headers(i)}
                            for i in range(search_requests)
                        ],
                        50,
                        400,
                    ),
                    (
                        "different_slots",
                        [
                            {
                                "method": "POST",
                                "url": "/api/v1/bookings",
                                "headers": headers(i),
                                "json": {"slot_id": str(data["slots"][i])},
                            }
                            for i in range(100)
                        ],
                        100,
                        600,
                    ),
                    (
                        "same_slot",
                        [
                            {
                                "method": "POST",
                                "url": "/api/v1/bookings",
                                "headers": headers(i),
                                "json": {"slot_id": str(data["slots"][100])},
                            }
                            for i in range(100)
                        ],
                        100,
                        None,
                    ),
                    (
                        "different_slots_idempotent",
                        [
                            {
                                "method": "POST",
                                "url": "/api/v1/bookings",
                                "headers": {
                                    **headers(i + 98),
                                    "Idempotency-Key": f"load-idempotency-{i}",
                                },
                                "json": {"slot_id": str(data["slots"][300 + i])},
                            }
                            for i in range(100)
                        ],
                        100,
                        600,
                    ),
                ]
                for name, jobs, count, target in scenarios:
                    if name == "different_slots":
                        for i in range(10):
                            warm = client.post(
                                "/api/v1/bookings",
                                headers=headers(i),
                                json={"slot_id": str(data["slots"][200 + i])},
                            )
                            if warm.status_code != 201:
                                raise RuntimeError("booking warmup failed; see server.txt")
                    print("Running " + name, flush=True)
                    measured = measure(client, jobs, count)
                    measured["target_p95_ms"] = target
                    expected = (
                        {"200": search_requests}
                        if name == "search"
                        else {"201": 100}
                        if name in {"different_slots", "different_slots_idempotent"}
                        else {"201": 1, "409": 99}
                    )
                    measured["passed"] = (
                        measured["statuses"] == {str(k): v for k, v in expected.items()}
                        and measured["invalid_bodies"] == 0
                        and (target is None or measured["p95_ms"] <= target)
                    )
                    result[name] = measured
                    (output / "results.json").write_text(
                        json.dumps(result, indent=2), encoding="utf-8"
                    )
                    print(
                        f"{name}: p95={measured['p95_ms']} ms, statuses={measured['statuses']}, passed={measured['passed']}",
                        flush=True,
                    )
                engine = create_engine(app_url, hide_parameters=True)
                try:
                    with engine.connect() as conn:
                        result["same_slot"]["confirmed_rows"] = conn.scalar(
                            select(func.count())
                            .select_from(t.bookings)
                            .where(
                                t.bookings.c.slot_id == data["slots"][100],
                                t.bookings.c.status == "confirmed",
                            )
                        )
                    result["same_slot"]["passed"] &= result["same_slot"]["confirmed_rows"] == 1
                    with engine.connect() as conn:
                        result["persisted"] = {
                            "bookings": conn.scalar(select(func.count()).select_from(t.bookings)),
                            "notifications": conn.scalar(
                                select(func.count()).select_from(t.notifications)
                            ),
                            "idempotency_keys": conn.scalar(
                                select(func.count()).select_from(t.idempotency)
                            ),
                        }
                finally:
                    engine.dispose()
                result["passed"] = all(result[name]["passed"] for name, *_ in scenarios)
                result["passed"] &= result["persisted"] == {
                    "bookings": 211,
                    "notifications": 633,
                    "idempotency_keys": 100,
                }
                (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                return result
    finally:
        if server is not None:
            if os.name == "nt":
                # The venv executable can be a redirector; stop its API child too.
                killer = Path(os.environ["SYSTEMROOT"]) / "System32/taskkill.exe"
                subprocess.run(  # noqa: S603 -- fixed OS utility and this process's child PID
                    [str(killer), "/PID", str(server.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=15,
                )  # nosec B603 -- fixed OS utility, own Popen PID
            else:
                server.terminate()
            server.wait(timeout=15)
        cluster.stop()
        target, parent = directory.resolve(), (ROOT / "pgdata").resolve()
        if target.parent != parent or not target.name.startswith("load-"):
            raise RuntimeError("refusing to remove a directory outside the isolated load workspace")
        if target.exists():
            shutil.rmtree(target)


def main() -> int:
    """Виміри з незміненими продуктовими порогами; код 1 означає невиконану ціль."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--search-requests", type=int, default=2000)
    parser.add_argument("--api-workers", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if args.search_requests < 50 or args.search_requests % 50:
        parser.error("search-requests must be a positive multiple of 50")
    return 0 if run(args.output, args.search_requests, args.api_workers)["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
