"""Regression: onboarding completion must win after the wizard's early
preferences write. Kept apart from ``test_users_repository.py`` so this file
imports only symbols that exist on the base revision — the regression-proof
lane runs it there and expects it to fail."""

import pytest

from app.db.repositories.users import UserRepository
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    UserDocument,
)


@pytest.fixture
def repo(raw_collection) -> UserRepository:
    return UserRepository()


@pytest.mark.regression
async def test_preferences_saved_before_completion_do_not_block_it(repo):
    """The wizard PATCHes the answers before payment, which creates the
    ``onboarding`` subdocument early. Completion must still win afterwards —
    gating on the subdocument's absence parked every new user on
    "Getting your chat ready" forever."""
    created = await repo.create(UserDocument.model_validate({"email": "gate@b.com", "name": "A"}))
    await repo.update_onboarding_preferences(
        created.id, OnboardingPreferences(profession="eng", needs=["inbox"])
    )
    completed = await repo.complete_onboarding(
        created.id,
        phase=OnboardingPhase.COMPLETED,
        bio_status=BioStatus.PENDING,
        preferences=OnboardingPreferences(profession="eng", needs=["inbox"]),
    )
    assert completed is not None
    assert completed.onboarding["completed"] is True
