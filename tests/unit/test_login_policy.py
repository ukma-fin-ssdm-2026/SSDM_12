"""Чисті правила cooldown та конфігурація незалежні від HTTP й PostgreSQL."""

from datetime import timedelta

import pytest

from api import clock
from api.config import Settings
from unislot.auth.domain.sessions import LoginAttempt, LoginPolicy

pytestmark = pytest.mark.req("FR-006", "SEC-001")


@pytest.mark.parametrize("values", [(0, 300), (5, 0), (-1, 1)])
def test_invalid_policy_is_rejected(values):
    with pytest.raises(ValueError, match="positive"):
        LoginPolicy(*values)


def test_expired_cooldown_starts_new_failure_cycle():
    policy, now = LoginPolicy(2, 10), clock.utc_now()
    attempt = LoginAttempt("dummy", 0, None)
    policy.record_failure(attempt, now)
    assert attempt.failures == 1 and attempt.blocked_until is None
    policy.record_failure(attempt, now)
    assert attempt.blocked_until == now + timedelta(seconds=10)
    policy.record_failure(attempt, now + timedelta(seconds=10))
    assert attempt.failures == 1 and attempt.blocked_until is None


@pytest.mark.parametrize(
    "change",
    [
        {"session_ttl_seconds": 0},
        {"login_max_failures": 0},
        {"login_cooldown_seconds": 0},
        {"cors_origins": ("*",)},
    ],
)
def test_auth_configuration_does_not_silently_disable_security(change):
    with pytest.raises(ValueError, match=r"positive|explicit origins"):
        Settings(
            **{
                "export_openapi_on_startup": False,
                "demo_auth_enabled": False,
                "cors_origins": (),
                **change,
            }
        )
