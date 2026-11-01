"""Ізольовані інваріанти ролей без FastAPI чи сховища."""

import pytest

from unislot.admin.domain.rules import LastAdmin, ProviderHasResources, ensure_role_revocable

pytestmark = pytest.mark.req("FR-062", "FR-063")


@pytest.mark.parametrize("count", [0, 1])
def test_last_admin_cannot_be_revoked(count: int) -> None:
    with pytest.raises(LastAdmin):
        ensure_role_revocable("admin", admin_count=count, resource_count=0)


def test_other_admin_allows_revocation() -> None:
    ensure_role_revocable("admin", admin_count=2, resource_count=0)


def test_provider_with_resources_cannot_be_revoked() -> None:
    with pytest.raises(ProviderHasResources):
        ensure_role_revocable("provider", admin_count=1, resource_count=1)


def test_provider_without_resources_can_be_revoked() -> None:
    ensure_role_revocable("provider", admin_count=1, resource_count=0)
