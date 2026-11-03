"""Стан автентифікації та тимчасові конфігуровані межі OQ-001/AQ-06."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4


@dataclass
class Credential:
    """Сервер зберігає лише Argon2id-хеш пароля."""

    user_id: UUID
    password_hash: str = field(repr=False)


@dataclass
class Session:
    """Непрозорі токени існують у браузері; у сховищі — тільки їхні хеші."""

    token_hash: str = field(repr=False)
    user_id: UUID
    csrf_hash: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)


@dataclass
class LoginAttempt:
    """Однакова форма лічильника для наявної й невідомої адреси."""

    key: str = field(repr=False)
    failures: int
    blocked_until: datetime | None
    last_failed_login_at: datetime | None = None


@dataclass(frozen=True)
class LoginPolicy:
    """Значення конфігурації не закривають продуктове питання OQ-001."""

    max_failures: int = 5
    cooldown_seconds: int = 300

    def __post_init__(self) -> None:
        """Некоректна конфігурація не вимикає захист непомітно."""
        if self.max_failures < 1 or self.cooldown_seconds < 1:
            raise ValueError("login policy values must be positive")

    def record_failure(self, attempt: LoginAttempt, now: datetime) -> None:
        """Новий цикл після cooldown; заблоковані запити його не продовжують."""
        if attempt.blocked_until is not None and now >= attempt.blocked_until:
            attempt.failures, attempt.blocked_until = 0, None
        attempt.failures += 1
        attempt.last_failed_login_at = now
        if attempt.failures >= self.max_failures:
            attempt.blocked_until = now + timedelta(seconds=self.cooldown_seconds)
