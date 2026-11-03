"""Process scheduling configuration must be bounded and restored on app shutdown."""

import sys

import pytest
from fastapi.testclient import TestClient

from api import main
from api.config import Settings, get_settings

pytestmark = pytest.mark.req("QA-12")


@pytest.mark.parametrize("milliseconds", [0, 21])
def test_thread_interval_configuration_rejects_out_of_bounds(milliseconds):
    with pytest.raises(ValueError, match="thread switch interval"):
        Settings(
            export_openapi_on_startup=False,
            demo_auth_enabled=False,
            cors_origins=(),
            thread_switch_interval_ms=milliseconds,
        )


@pytest.mark.parametrize("fail_startup", [False, True])
@pytest.mark.parametrize("milliseconds", [1, 20])
def test_lifespan_restores_process_interval_on_success_and_startup_failure(
    monkeypatch, fail_startup, milliseconds
):
    before = sys.getswitchinterval()
    monkeypatch.delenv("UNISLOT_DATABASE_URL", raising=False)
    monkeypatch.setenv("UNISLOT_THREAD_SWITCH_INTERVAL_MS", str(milliseconds))
    monkeypatch.setenv("UNISLOT_EXPORT_OPENAPI", "1" if fail_startup else "0")
    get_settings.cache_clear()

    def broken_export(app):
        raise RuntimeError("synthetic startup failure")

    def start():
        with TestClient(main.create_app()) as client:
            assert sys.getswitchinterval() == pytest.approx(
                milliseconds / 1000 if sys.platform == "win32" else before
            )
            assert client.get("/health").status_code == 200

    try:
        if fail_startup:
            monkeypatch.setattr(main.openapi_export, "write_artifacts", broken_export)
            with pytest.raises(RuntimeError, match="synthetic startup failure"):
                start()
        else:
            start()
    finally:
        get_settings.cache_clear()
    assert sys.getswitchinterval() == pytest.approx(before)
