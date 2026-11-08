"""Недоступний для запису `docs/api/` не повинен зупиняти старт API.

Лаб 9, Етап 3, знахідка R-08 у `docs/reliability/scavenger-hunt.md`. Дефект:
`export_openapi_on_startup` типово увімкнений, а `write_artifacts` робить `mkdir` і
`write_text` усередині `lifespan` без обробки помилок. На контейнері з файловою системою
лише для читання старт падав через побічну дію, не потрібну для обслуговування запитів.
`render.yaml` обходить це змінною `UNISLOT_EXPORT_OPENAPI=0` — тобто захист тримався на
правильно виставленій змінній, а не на коді.

Межа рішення: поглинається лише `OSError` (операційна причина — права, read-only, диск).
`RuntimeError` із генерації специфікації лишається фатальним, бо це дефект коду; це
перевіряє `test_thread_switch_interval.py::test_lifespan_restores_process_interval...`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import main
from api.config import get_settings

pytestmark = pytest.mark.req("QA-16")


@pytest.fixture(autouse=True)
def _export_enabled(monkeypatch):
    """Вмикаємо експорт специфікації — саме той шлях, що падав."""
    monkeypatch.delenv("UNISLOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("UNISLOT_EXPORT_OPENAPI", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "failure",
    [
        OSError(30, "Read-only file system"),
        PermissionError(13, "Permission denied"),
    ],
)
def test_api_still_serves_requests_when_spec_cannot_be_written(monkeypatch, caplog, failure):
    """Специфікація вже є в репозиторії; відмова запису — не причина не стартувати."""

    def read_only(app):
        raise failure

    monkeypatch.setattr(main.openapi_export, "write_artifacts", read_only)

    with caplog.at_level("WARNING", logger="unislot.api"), TestClient(main.create_app()) as client:
        assert client.get("/health").status_code == 200

    assert any(type(failure).__name__ in r.getMessage() for r in caplog.records), (
        "деградацію не записано в журнал — відмова стала невидимою"
    )


def test_spec_generation_defect_still_stops_startup(monkeypatch):
    """Ширший catch не повинен ховати дефект самої генерації специфікації."""

    def broken(app):
        raise RuntimeError("synthetic spec defect")

    monkeypatch.setattr(main.openapi_export, "write_artifacts", broken)

    with (
        pytest.raises(RuntimeError, match="synthetic spec defect"),
        TestClient(main.create_app()) as client,
    ):
        client.get("/health")
