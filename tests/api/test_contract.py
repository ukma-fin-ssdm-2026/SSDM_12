"""Контракт-тести специфікації: повнота анотацій і єдиний формат помилок (Лаб 4).

Ці тести не знають про конкретні кінцеві точки — вони проходять по всій згенерованій
специфікації. Нова кінцева точка без опису, без прикладу помилки чи без перевірки прав
ламає збірку автоматично: це критерій «Повнота анотацій» Лаб 4, перетворений на
fitness-функцію (Лекція 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from api import clock
from api.main import create_app
from api.openapi_export import render_spec_yaml

pytestmark = pytest.mark.req("QA-10")

PUBLIC_OPERATIONS = {"get_health"}  # єдиний виняток із deny-by-default
METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return create_app().openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in METHODS
    ]


def test_every_operation_is_documented(spec: dict[str, Any]) -> None:
    declared_tags = {t["name"] for t in spec["tags"]}
    for path, method, op in operations(spec):
        where = f"{method.upper()} {path}"
        # Без summary FastAPI сам робить його з імені функції: cancel_booking → «Cancel Booking».
        # Такий summary непорожній, тож перевіряємо саме, що його написав автор.
        auto_summary = op["operationId"].replace("_", " ").title()
        assert op.get("summary") not in (None, "", auto_summary), f"{where}: немає summary"
        assert len(op.get("description", "")) >= 40, f"{where}: опис коротший за 40 символів"
        assert len(op.get("tags", [])) == 1 and op["tags"][0] in declared_tags, f"{where}: тег"
        for status, response in op["responses"].items():
            assert response.get("description") not in ("", "Successful Response"), (
                f"{where} {status}: опис відповіді за замовчуванням"
            )


def test_operation_ids_are_unique_function_names(spec: dict[str, Any]) -> None:
    ids = [op["operationId"] for _, _, op in operations(spec)]
    assert len(ids) == len(set(ids))
    assert all(i.isidentifier() and "api_v1" not in i for i in ids), ids


def test_every_parameter_has_description(spec: dict[str, Any]) -> None:
    for path, method, op in operations(spec):
        for param in op.get("parameters", []):
            assert param.get("description"), f"{method.upper()} {path}: {param['name']} без опису"


@pytest.mark.req("QA-09")
def test_errors_use_problem_json_with_examples(spec: dict[str, Any]) -> None:
    for path, method, op in operations(spec):
        for status, response in op["responses"].items():
            if status[0] not in "45":
                continue
            content = response.get("content", {})
            where = f"{method.upper()} {path} {status}"
            assert list(content) == ["application/problem+json"], f"{where}: {list(content)}"
            media = content["application/problem+json"]
            assert media["schema"] == {"$ref": "#/components/schemas/Problem"}, where
            assert media.get("examples"), f"{where}: немає прикладу помилки"


@pytest.mark.req("QA-07", "SEC-002")
def test_protected_operations_declare_auth_and_401(spec: dict[str, Any]) -> None:
    for path, method, op in operations(spec):
        if op["operationId"] in PUBLIC_OPERATIONS:
            continue
        where = f"{method.upper()} {path}"
        assert op.get("security") == [{"demoBearer": []}], f"{where}: немає вимоги автентифікації"
        assert "401" in op["responses"], f"{where}: не задокументовано 401"


@pytest.mark.req("QA-06")
def test_operations_with_input_document_422(spec: dict[str, Any]) -> None:
    for path, method, op in operations(spec):
        if op.get("parameters") or op.get("requestBody"):
            assert "422" in op["responses"], f"{method.upper()} {path}: не задокументовано 422"


@pytest.mark.req("QA-06")
def test_no_default_fastapi_validation_schema(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_every_schema_property_has_description(spec: dict[str, Any]) -> None:
    for name, schema in spec["components"]["schemas"].items():
        for prop, body in schema.get("properties", {}).items():
            assert body.get("description"), f"{name}.{prop} без опису"


def test_request_bodies_have_named_examples(spec: dict[str, Any]) -> None:
    for path, method, op in operations(spec):
        if "requestBody" in op:
            media = op["requestBody"]["content"]["application/json"]
            assert media.get("examples"), f"{method.upper()} {path}: немає прикладів тіла запиту"


def test_spec_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Специфікація не залежить від часу генерації — інакше перевірка розходження в CI
    падала б без змін у коді."""
    first = render_spec_yaml(create_app())
    monkeypatch.setattr(clock, "utc_now", lambda: datetime(2027, 3, 1, 12, 0, tzinfo=UTC))
    assert render_spec_yaml(create_app()) == first
