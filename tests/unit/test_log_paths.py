"""Шаблон маршруту для журналу доступу: ідентифікатори не потрапляють у лог."""

from api.log_paths import route_template


def test_path_without_identifiers_is_unchanged():
    assert route_template("/api/v1/slots") == "/api/v1/slots"


def test_booking_identifier_becomes_placeholder():
    path = "/api/v1/bookings/3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert route_template(path) == "/api/v1/bookings/{id}"


def test_identifier_in_the_middle_of_a_path():
    path = "/api/v1/resources/3fa85f64-5717-4562-b3fc-2c963f66afa6/slots"
    assert route_template(path) == "/api/v1/resources/{id}/slots"
