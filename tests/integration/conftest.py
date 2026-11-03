"""Справжній PostgreSQL у власному кластері: без системного сервісу й чужих даних."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from api.infrastructure.postgres import PostgresStore
from api.stubs.store import store
from scripts.manage_db import migrate, seed_demo
from scripts.postgres_dev import LocalCluster

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_cluster():
    directory = ROOT / "pgdata" / ("tests-" + uuid.uuid4().hex)
    cluster = LocalCluster(directory)
    try:
        cluster.start()
        yield cluster
    finally:
        cluster.stop()
        # The only recursive removal is this newly generated directory under pgdata.
        target, parent = directory.resolve(), (ROOT / "pgdata").resolve()
        assert target.parent == parent and target.name.startswith("tests-")
        shutil.rmtree(target)


@pytest.fixture
def database(frozen_world, pg_cluster):
    suffix = uuid.uuid4().hex
    name, role = "test_" + suffix, "app_" + suffix
    owner_url, app_url = pg_cluster.create_database(name, role)
    owner, backend, previous = None, None, None
    try:
        migrate(owner_url, role)
        assert seed_demo(app_url)
        backend = PostgresStore(app_url)
        owner = create_engine(owner_url, hide_parameters=True)
        previous = store.set_backend(backend)
        with store.lock:
            pass

        # URL is held only in memory; default repr of this fixture never prints secrets.
        class Database(SimpleNamespace):
            def __repr__(self):
                return "<isolated PostgreSQL test database>"

        yield Database(
            backend=backend, owner=owner, app_url=app_url, owner_url=owner_url, role=role
        )
    finally:
        if previous is not None:
            store.set_backend(previous)
        if backend is not None:
            backend.close()
        if owner is not None:
            owner.dispose()
        pg_cluster.drop_database(name, role)
