"""Журнал доступу не містить ідентифікаторів зі шляху (THR-09, CWE-532)."""

import json
import logging
import uuid

import pytest

pytestmark = pytest.mark.req("THR-09")

STUDENT = {"Authorization": "Bearer demo-student"}


def test_access_log_records_the_route_template(client, caplog):
    booking_id = uuid.UUID(int=0)
    with caplog.at_level(logging.INFO, logger="unislot.access"):
        client.get(f"/api/v1/bookings/{booking_id}", headers=STUDENT)

    entries = [json.loads(r.message) for r in caplog.records if r.name == "unislot.access"]
    assert len(entries) == 1
    assert entries[0]["path"] == "/api/v1/bookings/{id}"
    assert str(booking_id) not in entries[0]["path"]
