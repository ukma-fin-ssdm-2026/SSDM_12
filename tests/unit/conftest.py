"""Lab6: isolated service tests, synthetic identities and a frozen clock.

AI-assisted local draft: Codex. Human owners and review steps are in Labs/Lab06/README.md.
"""

from __future__ import annotations

import pytest

from api import clock
from api.security import CurrentUser
from api.stubs.store import Ids, store


@pytest.fixture
def now():
    return clock.utc_now()


@pytest.fixture
def actor():
    """Create an identity from the reset, in-memory fixture; no HTTP dependency."""

    def make(user_id):
        user = store.users[user_id]
        return CurrentUser(user.id, user.full_name, user.email, user.roles)

    return make


@pytest.fixture
def student(actor):
    return actor(Ids.STUDENT)


@pytest.fixture
def other_student(actor):
    return actor(Ids.STUDENT_2)


@pytest.fixture
def provider(actor):
    return actor(Ids.PROVIDER)


@pytest.fixture
def admin(actor):
    return actor(Ids.ADMIN)
