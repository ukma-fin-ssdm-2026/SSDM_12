"""Характеризація `api.main.custom_openapi` перед рефакторингом (Лаб 8, R-4).

Наш застосунок не має жодної захищеної операції зміни без власної відповіді 403, тому гілку
«додати 403 для CSRF з нуля» ніхто не виконував: покриття показувало її пропущеною, і
`export_openapi.py --check` її не захищає. Тест фіксує поточну поведінку на маленькому
застосунку: що додається до операцій із `security` і чого не торкається решта.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.security import HTTPBearer

from api.errors import PROBLEM_MEDIA_TYPE, ErrorCode, problem_responses
from api.main import custom_openapi

pytestmark = pytest.mark.req("QA-10")

BEARER = HTTPBearer()


@pytest.fixture
def schema():
    app = FastAPI(title="t", version="1")

    @app.post("/things", dependencies=[Depends(BEARER)])
    def create_thing() -> dict:
        return {}

    @app.get("/things", dependencies=[Depends(BEARER)])
    def list_things() -> dict:
        return {}

    @app.get("/health")
    def health() -> dict:
        return {}

    return custom_openapi(app)


def test_unsafe_operation_without_403_gets_the_csrf_403_from_the_catalog(schema):
    expected = problem_responses(ErrorCode.CSRF_FAILED)[403]
    response = schema["paths"]["/things"]["post"]["responses"]["403"]
    assert set(response) == {"description", "content"}
    assert response["description"] == expected["description"]
    assert list(response["content"]) == [PROBLEM_MEDIA_TYPE]
    media = response["content"][PROBLEM_MEDIA_TYPE]
    assert media["schema"] == {"$ref": "#/components/schemas/Problem"}
    assert media["examples"] == expected["content"]["application/json"]["examples"]


def test_unsafe_operation_documents_the_optional_csrf_header_once(schema):
    parameters = schema["paths"]["/things"]["post"]["parameters"]
    assert parameters == [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": False,
            "description": "Обов'язковий для cookie-сесії; значення з /auth/login або "
            "unislot_csrf cookie. Для явно ввімкненого demoBearer не потрібний.",
            "schema": {"type": "string", "minLength": 43, "maxLength": 43},
        }
    ]


def test_every_secured_operation_gets_503_and_only_unsafe_ones_get_csrf(schema):
    post, get = schema["paths"]["/things"]["post"], schema["paths"]["/things"]["get"]
    for operation in (post, get):
        unavailable = operation["responses"]["503"]
        assert list(unavailable["content"]) == [PROBLEM_MEDIA_TYPE]
        assert unavailable["content"][PROBLEM_MEDIA_TYPE]["schema"] == {
            "$ref": "#/components/schemas/Problem"
        }
    assert "403" not in get["responses"]
    assert "parameters" not in get


def test_public_operation_is_left_untouched(schema):
    health = schema["paths"]["/health"]["get"]
    assert set(health["responses"]) == {"200"}
    assert "parameters" not in health


def test_schema_is_built_once_and_cached():
    app = FastAPI(title="t", version="1")
    first = custom_openapi(app)
    assert custom_openapi(app) is first
