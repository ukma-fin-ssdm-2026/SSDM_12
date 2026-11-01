"""Інваріанти зміни ролей (FR-063, INV-15); параметри передає application-шар."""

from __future__ import annotations

from unislot.platform.errors import DomainError


class LastAdmin(DomainError):
    """Не можна забрати останнього адміністратора системи."""

    code = "LAST_ADMIN"


class ProviderHasResources(DomainError):
    """Ресурси треба перепризначити до відкликання ролі провайдера (INV-15)."""

    code = "PROVIDER_HAS_RESOURCES"


def ensure_role_revocable(role: str, *, admin_count: int, resource_count: int) -> None:
    """Відхиляє зміну, яка лишає систему без адміністратора чи ресурс без провайдера."""
    if role == "admin" and admin_count <= 1:
        raise LastAdmin
    if role == "provider" and resource_count:
        raise ProviderHasResources
