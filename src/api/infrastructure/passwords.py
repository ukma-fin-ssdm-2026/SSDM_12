"""Argon2id із зафіксованим RFC 9106 low-memory профілем; без обрізання пароля."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
# Невідомий користувач проходить таку саму дорогу перевірку, як неправильний пароль.
# Випадковий dummy не є обліковим записом і ніколи не дає успішний вхід.
_DUMMY = hasher.hash(secrets.token_urlsafe(32))
UNUSABLE_HASH = hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Хешує повний Unicode-рядок із новою випадковою сіллю."""
    return hasher.hash(password)


def password_matches(encoded: str | None, password: str) -> bool:
    """Одна перевірка Argon2; для відсутнього хеша результат завжди False."""
    try:
        verified = hasher.verify(encoded or _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False
    return verified and encoded is not None
