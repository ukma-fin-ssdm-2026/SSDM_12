"""Межі повторів доставки без HTTP та PostgreSQL."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import DBAPIError

from api import clock
from api.infrastructure.outbox import (
    DeliveryUnavailable,
    MailboxGateway,
    MemoryOutbox,
    dispatch_due,
)
from unislot.notifications.domain.model import RetryPolicy

pytestmark = pytest.mark.req("FR-053", "REL-002")


@pytest.mark.parametrize("field", ["max_attempts", "base_delay", "max_delay", "lease_seconds"])
def test_policy_rejects_nonpositive_values(field):
    with pytest.raises(ValueError, match="positive"):
        RetryPolicy(**{field: 0})


def test_backoff_is_bounded_even_for_huge_attempt_count():
    policy, now = RetryPolicy(), clock.utc_now()
    assert policy.next_attempt(now, 1) == now + timedelta(seconds=5)
    assert policy.next_attempt(now, 2) == now + timedelta(seconds=10)
    assert policy.next_attempt(now, 10**9) == now + timedelta(seconds=3600)


@pytest.mark.parametrize("batch", [0, 101])
def test_dispatch_rejects_invalid_batch_size(batch):
    with pytest.raises(ValueError, match="batch"):
        dispatch_due(MemoryOutbox(), clock.utc_now(), batch=batch)


def test_gateway_hides_database_driver_errors():
    class BrokenInbox:
        def deliver(self, notice, now):
            raise DBAPIError(None, None, RuntimeError("driver details"))

    with pytest.raises(DeliveryUnavailable):
        MailboxGateway(BrokenInbox()).send(None, clock.utc_now())
