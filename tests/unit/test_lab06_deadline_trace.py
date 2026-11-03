"""Автоматизоване трасування межі скасування для Лаб6 (не сесія людини в IDE).

Підготовлено ChatGPT (OpenAI) для діагностики без клавіші F9.
"""

from __future__ import annotations

import json
import linecache
import sys

import pytest

from api.enums import BookingStatus
from api.stubs import booking_service as service
from api.stubs.store import Ids, store
from unislot.booking.domain import rules


@pytest.mark.req("FR-041", "TP-01")
def test_exact_deadline_trace(student, record_property):
    """Зняти реальні локальні змінні й стек при виконанні доменного правила."""
    booking = store.bookings[Ids.BOOKING_ACTIVE]
    deadline = booking.cancel_deadline_at
    code = rules.ensure_changeable.__code__
    expected_line = "if now > deadline:"
    breakpoint_line = next(
        (
            n
            for n in range(code.co_firstlineno, code.co_firstlineno + 35)
            if linecache.getline(code.co_filename, n).strip() == expected_line
        ),
        None,
    )
    assert breakpoint_line is not None, "Deadline rule moved or changed"
    observations = []

    def trace(frame, event, _arg):
        if frame.f_code is code and event == "line" and frame.f_lineno == breakpoint_line:
            stack = []
            current = frame
            while current is not None and len(stack) < 8:
                stack.append(current.f_code.co_name)
                if current.f_code.co_name == "test_exact_deadline_trace":
                    break
                current = current.f_back
            observations.append(
                {
                    "line": frame.f_lineno,
                    "now": frame.f_locals["now"].isoformat(),
                    "deadline": frame.f_locals["deadline"].isoformat(),
                    "equal": frame.f_locals["now"] == frame.f_locals["deadline"],
                    "call_stack": stack,
                }
            )
        return trace

    prior_trace = sys.gettrace()
    try:
        sys.settrace(trace)
        result = service.cancel(student, booking.id, deadline)
    finally:
        sys.settrace(prior_trace)

    assert result.status is BookingStatus.CANCELLED
    assert len(observations) == 1, "Deadline branch must be visited exactly once"
    snapshot = observations[0]
    assert snapshot["equal"] is True
    assert snapshot["call_stack"][:3] == [
        "ensure_changeable",
        "_check_changeable",
        "cancel",
    ]
    assert "test_exact_deadline_trace" in snapshot["call_stack"]
    record_property("lab06_automated_deadline_trace", json.dumps(snapshot, ensure_ascii=False))
