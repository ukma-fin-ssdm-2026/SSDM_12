"""Потокова передача ASGI, ізоляція запитів і приватність журналу."""

import asyncio
import json
import logging

import pytest

from api.config import API_VERSION
from api.middleware import RequestContextMiddleware

pytestmark = pytest.mark.req("THR-09", "QA-08")


def entries(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == "unislot.access"]


def test_interleaved_streams_keep_own_headers_identity_and_private_log(caplog):
    forwarded = {"a": [], "b": []}

    async def receive():
        raise AssertionError("the wrapper must not consume a request body")

    async def application(scope, receive, send):
        label = scope["label"]
        scope["state"]["user_id"] = label
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"x-test", b"kept")]}
        )
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        assert forwarded[label][-1]["body"] == b"first"
        await asyncio.sleep(0)
        await send({"type": "http.response.body", "body": b"last", "more_body": False})

    middleware = RequestContextMiddleware(application)

    async def request(label):
        async def send(message):
            forwarded[label].append(message)

        await middleware(
            {
                "type": "http",
                "label": label,
                "method": "GET",
                "path": "/api/v1/bookings/00000000-0000-0000-0000-000000000000",
                "query_string": b"private-filter=not-for-log",
                "headers": [
                    (b"x-request-id", (label * 32).encode()),
                    (b"cookie", b"dummy-session"),
                ],
            },
            receive,
            send,
        )

    async def concurrent_requests():
        await asyncio.gather(request("a"), request("b"))

    with caplog.at_level(logging.INFO, logger="unislot.access"):
        asyncio.run(concurrent_requests())
    rows = entries(caplog)
    assert len(rows) == 2
    assert {r["request_id"]: r["user_id"] for r in rows} == {"a" * 32: "a", "b" * 32: "b"}
    for label, messages in forwarded.items():
        headers = dict(messages[0]["headers"])
        assert headers[b"x-request-id"] == (label * 32).encode()
        assert headers[b"api-version"].decode() == API_VERSION
        assert headers[b"cache-control"] == b"no-store"
        assert headers[b"x-test"] == b"kept"
        assert [m["body"] for m in messages[1:]] == [b"first", b"last"]
    assert all(r["path"] == "/api/v1/bookings/{id}" for r in rows)
    assert "dummy-session" not in caplog.text and "private-filter" not in caplog.text


def test_lifespan_is_forwarded_without_http_fields_or_access_log(caplog):
    messages = []

    async def application(scope, receive, send):
        assert scope == {"type": "lifespan"}
        await send({"type": "lifespan.startup.complete"})

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        messages.append(message)

    with caplog.at_level(logging.INFO, logger="unislot.access"):
        asyncio.run(RequestContextMiddleware(application)({"type": "lifespan"}, receive, send))
    assert messages == [{"type": "lifespan.startup.complete"}]
    assert entries(caplog) == []


def test_unhandled_failure_logs_one_500_without_exception_detail(caplog):
    async def broken(scope, receive, send):
        raise RuntimeError("private exception detail")

    async def unused():
        raise AssertionError("not called")

    with caplog.at_level(logging.INFO, logger="unislot.access"), pytest.raises(RuntimeError):
        asyncio.run(
            RequestContextMiddleware(broken)(
                {"type": "http", "method": "GET", "path": "/health", "headers": []}, unused, unused
            )
        )
    assert [r["status"] for r in entries(caplog)] == [500]
    assert "private exception detail" not in caplog.text
