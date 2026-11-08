import asyncio
import json

import pytest
from psycopg import OperationalError

from scripts import check_readiness

pytestmark = pytest.mark.req("QA-21")


@pytest.fixture
def postgres_url(monkeypatch):
    monkeypatch.setenv("UNISLOT_DATABASE_URL", "postgresql+psycopg://localhost/unislot_test")


@pytest.mark.usefixtures("postgres_url")
def test_transient_error_can_recover(monkeypatch, capsys):
    calls = 0

    async def select_one(conninfo):
        nonlocal calls
        assert "dbname=unislot_test" in conninfo
        calls += 1
        if calls == 1:
            raise OperationalError("injected dependency failure")

    monkeypatch.setattr(check_readiness, "_select_one", select_one)
    monkeypatch.setattr(check_readiness, "BASE_BACKOFF_SECONDS", 0.0)

    assert check_readiness.main([]) == 0
    assert calls == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "healthy",
        "dependency": "postgresql",
        "attempts": 2,
    }


@pytest.mark.usefixtures("postgres_url")
def test_unavailable_dependency_stops_after_three_attempts(monkeypatch, capsys):
    calls = 0
    windows = []
    delays = []

    async def select_one(_conninfo):
        nonlocal calls
        calls += 1
        raise OperationalError("injected dependency failure")

    def uniform(low, high):
        windows.append((low, high))
        return high / 2

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(check_readiness, "_select_one", select_one)
    monkeypatch.setattr(check_readiness._random, "uniform", uniform)
    monkeypatch.setattr(check_readiness.asyncio, "sleep", sleep)

    assert check_readiness.main([]) == 1
    assert calls == 3
    assert windows == [(0.0, 0.1), (0.0, 0.2)]
    assert delays == [0.05, 0.1]
    assert json.loads(capsys.readouterr().out) == {
        "status": "unhealthy",
        "dependency": "postgresql",
        "attempts": 3,
    }


@pytest.mark.usefixtures("postgres_url")
def test_per_attempt_timeout_cancels_stalled_probe(monkeypatch, capsys):
    cancellations = 0

    async def select_one(_conninfo):
        nonlocal cancellations
        try:
            await asyncio.Future()
        finally:
            cancellations += 1

    monkeypatch.setattr(check_readiness, "_select_one", select_one)
    monkeypatch.setattr(check_readiness, "ATTEMPT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(check_readiness, "BASE_BACKOFF_SECONDS", 0.0)

    assert check_readiness.main([]) == 1
    assert cancellations == 3
    assert json.loads(capsys.readouterr().out)["status"] == "unhealthy"


@pytest.mark.parametrize("url", ["", "sqlite:///unislot.db"])
def test_missing_or_unsupported_url_is_misconfigured(monkeypatch, capsys, url):
    async def select_one(_conninfo):
        pytest.fail("invalid configuration must not connect to a database")

    monkeypatch.setattr(check_readiness, "_select_one", select_one)
    monkeypatch.setenv("UNISLOT_DATABASE_URL", url)

    assert check_readiness.main([]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "misconfigured",
        "dependency": "postgresql",
    }
