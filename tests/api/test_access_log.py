"""Журнал доступу не містить ідентифікаторів зі шляху (THR-09, CWE-532).

Використання ШІ: ціль циклу, план, реалізацію й тести написав Claude (Opus 5);
виконання, перевірку кожного RED/GREEN і володіння результатом — Никита.
Повний опис: docs/testing/testing-strategy.md, розділ «Використання ШІ».
"""

import json
import logging
import uuid

STUDENT = {"Authorization": "Bearer demo-student"}


class _Collector(logging.Handler):
    """Збирає записи одного логера, не залежачи від плагіна логування pytest."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_access_log_records_the_route_template(client):
    """Шлях у журналі — шаблон, а не конкретний ідентифікатор."""
    booking_id = uuid.UUID(int=0)
    # Хендлер вішаємо на сам логер: `configure_logging` ставить
    # `unislot.propagate = False`, тож через корінь записи не дійдуть, а
    # вбудований `caplog` у різних версіях pytest ловить їх по-різному.
    access = logging.getLogger("unislot.access")
    collector = _Collector()
    previous_level = access.level
    access.addHandler(collector)
    access.setLevel(logging.INFO)
    try:
        client.get(f"/api/v1/bookings/{booking_id}", headers=STUDENT)
    finally:
        access.removeHandler(collector)
        access.setLevel(previous_level)

    entries = [json.loads(r.getMessage()) for r in collector.records]
    assert len(entries) == 1
    assert entries[0]["path"] == "/api/v1/bookings/{id}"
    assert str(booking_id) not in entries[0]["path"]
