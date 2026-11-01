"""Auth REST API: самореєстрація, парольний вхід, серверні сесії й вихід (FR-001…007)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Request, Response

from api import clock
from api.config import API_PREFIX, get_settings
from api.errors import ErrorCode, problem_response, problem_responses
from api.infrastructure.unit_of_work import transactional
from api.schemas.auth import LoginIn, LoginOut, MeOut, RegisterIn
from api.security import AnyUser, check_public_auth_request
from api.services import auth_service as service

TAG = {
    "name": "auth",
    "description": "Самореєстрація студентів, парольний вхід і cookie-сесії (FR-001…007).",
}

router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=[TAG["name"]])


@router.get(
    "/me",
    response_model=MeOut,
    summary="Отримати поточного користувача",
    response_description="Поточний користувач і його ролі.",
    responses=problem_responses(ErrorCode.AUTH_REQUIRED),
)
@transactional
def get_me(user: AnyUser) -> MeOut:
    """Повертає ідентифікатор, ім'я, e-mail і ролі користувача, від імені якого надіслано
    запит. Клієнт використовує ролі, щоб показати лише доступні дії; перевіряє права
    все одно сервер (deny-by-default).
    """
    return MeOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        roles=sorted(user.roles, key=lambda r: r.value),
    )


def _me(user) -> MeOut:
    return MeOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        roles=sorted(user.roles, key=lambda role: role.value),
    )


@router.post(
    "/register",
    status_code=201,
    response_model=MeOut,
    summary="Зареєструвати обліковий запис студента",
    response_description="Новий користувач із єдиною роллю student.",
    responses=problem_responses(
        ErrorCode.EMAIL_ALREADY_REGISTERED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.TRANSIENT_CONFLICT,
    ),
)
@transactional
def register_user(
    request: Request,
    payload: Annotated[
        RegisterIn,
        Body(
            openapi_examples={
                "student": {
                    "summary": "Новий студент; пароль — навчальний приклад",
                    "value": {
                        "full_name": "Тестовий студент",
                        "email": "student@example.com",
                        "password": "demo phrase for registration",  # nosec B105 -- OpenAPI example only  # pragma: allowlist secret -- isolated example/test input
                    },
                }
            }
        ),
    ],
) -> MeOut:
    """Створює лише student незалежно від переданих role/roles. Адреса порівнюється
    без регістру; пароль хешується Argon2id без обрізання. Володіння поштою не
    підтверджується за C-002. Для входу після реєстрації викличте /auth/login.
    """
    check_public_auth_request(request)
    return _me(
        service.register(payload.full_name, str(payload.email), payload.password.get_secret_value())
    )


@router.post(
    "/login",
    response_model=LoginOut,
    summary="Увійти з адресою та паролем",
    response_description="Користувач, CSRF-токен та HttpOnly cookie-сесія.",
    responses=problem_responses(
        ErrorCode.INVALID_CREDENTIALS,
        ErrorCode.LOGIN_THROTTLED,
        ErrorCode.CSRF_FAILED,
        ErrorCode.VALIDATION_FAILED,
        ErrorCode.TRANSIENT_CONFLICT,
    ),
)
@transactional
def login_user(
    request: Request,
    response: Response,
    payload: Annotated[
        LoginIn,
        Body(
            openapi_examples={
                "student": {
                    "summary": "Раніше зареєстрований студент",
                    "value": {
                        "email": "student@example.com",
                        "password": "demo phrase for registration",  # nosec B105 -- OpenAPI example only  # pragma: allowlist secret -- isolated example/test input
                    },
                }
            }
        ),
    ],
):
    """Видає нову cookie-сесію, попередню поточну сесію відкликає. Однакова помилка
    для відсутньої адреси й неправильного пароля. Обмеження спроб зберігається в БД;
    параметри локальні до рішення OQ-001. Запити входу приймаються лише як JSON.
    """
    check_public_auth_request(request)
    result = service.login(
        str(payload.email),
        payload.password.get_secret_value(),
        clock.utc_now(),
        request.cookies.get(service.SESSION_COOKIE),
    )
    if result.error:
        headers = (
            {"Retry-After": str(result.retry_after)}
            if result.retry_after
            else {"WWW-Authenticate": 'Cookie realm="unislot"'}
        )
        return problem_response(request, result.error, headers=headers)
    settings = get_settings()
    for name, value, http_only in (
        (service.SESSION_COOKIE, result.token, True),
        (service.CSRF_COOKIE, result.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=settings.session_ttl_seconds,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=http_only,
            samesite="lax",
        )
    return LoginOut(
        user=_me(result.user), csrf_token=result.csrf_token, expires_at=result.session.expires_at
    )


@router.post(
    "/logout",
    status_code=204,
    summary="Вийти з поточної сесії",
    response_description="Сесію відкликано, обидві cookie видалено.",
    responses=problem_responses(
        ErrorCode.AUTH_REQUIRED, ErrorCode.CSRF_FAILED, ErrorCode.VALIDATION_FAILED
    ),
)
@transactional
def logout_user(request: Request, user: AnyUser) -> Response:
    """Відкликає серверну сесію та видаляє cookie. Для cookie-автентифікації потрібен
    X-CSRF-Token; чужі активні сесії цього користувача залишаються чинними.
    """
    service.logout(request.cookies.get(service.SESSION_COOKIE))
    response = Response(status_code=204)
    for name in (service.SESSION_COOKIE, service.CSRF_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            secure=get_settings().session_cookie_secure,
            httponly=name == service.SESSION_COOKIE,
            samesite="lax",
        )
    return response
