"""Невдала доставка залишає слід: клас помилки в журналі, код причини в `last_error`.

Лаб 9, Етап 3, знахідка R-02 у `docs/reliability/scavenger-hunt.md`. Дефект: три
механізми поспіль відкидали інформацію про причину — `raise DeliveryUnavailable from None`
губило `__cause__`, `except (...)` у `dispatch_due` не логував нічого, а `_finish`
записував стале `last_error = "gateway_unavailable"` незалежно від того, що сталося.
Повідомлення тихо повторювалися до `max_attempts` і ставали `failed` без діагностики.

Межа рішення: у журнал ідуть лише **назви класів** помилок, не їхній текст (CWE-532,
THR-09), а `last_error` лишається коротким стабільним кодом, бо потрапляє в аудит
і до оператора (CWE-209, стовпець `String(64)`).
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from api import clock
from api.infrastructure.outbox import (
    DeliveryUnavailable,
    MailboxGateway,
    dispatch_due,
)
from unislot.notifications.domain.model import Notification, RetryPolicy

pytestmark = pytest.mark.req("REL-002")


def _notice() -> Notification:
    return Notification(
        id=uuid.uuid4(),
        booking_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        kind="confirmation",
        payload={"subject": "не має потрапити в журнал"},
        scheduled_for=clock.utc_now(),
        status="sending",
        attempts=1,
        claim_token=uuid.uuid4(),
    )


class _Repository:
    """Мінімальний outbox: фіксує, з якою причиною Worker закрив спробу."""

    def __init__(self, notice: Notification, failure: BaseException) -> None:
        self.notice, self.failure, self.finished = notice, failure, []

    def claim(self, now, batch, policy):
        return [self.notice]

    def deliver(self, notice, now):
        raise self.failure

    def finish(self, notice, now, policy, error, reason=None):
        self.finished.append({"error": error, "reason": reason})


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (DeliveryUnavailable(), "gateway_unavailable"),
        (TimeoutError("провайдер не відповів"), "gateway_timeout"),
        (OSError("connection reset"), "gateway_network_error"),
    ],
)
def test_failure_reason_reaches_last_error_as_a_distinct_code(failure, code):
    """Оператор має відрізняти «провайдер недоступний» від таймауту й від мережі."""
    notice = _notice()
    repository = _Repository(notice, failure)

    result = dispatch_due(repository, clock.utc_now(), gateway=_Gateway(failure))

    assert result.failed == 1
    assert repository.finished == [{"error": True, "reason": code}]


class _Gateway:
    """Адаптер, що завжди падає заданою помилкою."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    def send(self, notice, now):
        raise self.failure


def test_failed_delivery_is_logged_with_the_exception_class(caplog):
    """Без запису в журнал причину відмови неможливо встановити після факту."""
    notice = _notice()
    repository = _Repository(notice, TimeoutError())

    with caplog.at_level(logging.WARNING, logger="unislot.outbox"):
        dispatch_due(repository, clock.utc_now(), gateway=_Gateway(TimeoutError()))

    records = [r for r in caplog.records if r.name == "unislot.outbox"]
    assert records, "невдала доставка не залишила жодного запису в журналі"
    event = json.loads(records[0].getMessage())
    assert event["code"] == "gateway_timeout"
    assert event["error"] == "TimeoutError"
    assert event["notification_id"] == str(notice.id)
    assert event["attempts"] == 1


def test_log_record_carries_no_message_body(caplog):
    """Тіло повідомлення — персональні дані; у журналі його бути не має (THR-09)."""
    notice = _notice()
    repository = _Repository(notice, DeliveryUnavailable())

    with caplog.at_level(logging.WARNING, logger="unislot.outbox"):
        dispatch_due(repository, clock.utc_now(), gateway=_Gateway(DeliveryUnavailable()))

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "не має потрапити в журнал" not in logged


def test_gateway_keeps_the_database_error_as_cause():
    """`from None` робив першопричину недосяжною навіть для обробника вище."""

    class BrokenInbox:
        def deliver(self, notice, now):
            raise DBAPIError("SELECT 1", None, RuntimeError("driver details"))

    with pytest.raises(DeliveryUnavailable) as caught:
        MailboxGateway(BrokenInbox()).send(_notice(), clock.utc_now())

    assert isinstance(caught.value.__cause__, DBAPIError)


def test_successful_delivery_records_no_failure_reason():
    """Регресія: успішна доставка не має записувати код причини."""
    notice = _notice()
    repository = _Repository(notice, DeliveryUnavailable())

    class Working:
        def send(self, notice, now):
            return True

    result = dispatch_due(repository, clock.utc_now(), gateway=Working(), policy=RetryPolicy())

    assert result.sent == 1
    assert repository.finished == [{"error": False, "reason": None}]
