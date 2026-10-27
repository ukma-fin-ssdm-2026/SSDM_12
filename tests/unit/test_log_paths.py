"""Шаблон маршруту для журналу доступу: ідентифікатори не потрапляють у лог."""

from api.log_paths import route_template


def test_path_without_identifiers_is_unchanged():
    assert route_template("/api/v1/slots") == "/api/v1/slots"
