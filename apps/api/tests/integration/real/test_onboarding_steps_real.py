"""Onboarding wizard steps against REAL MongoDB: each step's event fires once per onboarding run.

The step gate is a conditional $set on users.onboarding.steps_reached, so only a
real Mongo proves a replayed report cannot fire twice. PostHog is the one
substituted seam.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from unittest.mock import MagicMock, patch

from bson import ObjectId
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.redis import delete_cache
from app.db.repositories.users import user_repository
from app.models.user_models import OnboardingAnswers, OnboardingNeed
from app.services.onboarding import onboarding_service
from shared.py.analytics import UserId
from shared.py.analytics.catalog.onboarding import (
    OnboardingPhaseCompleted,
    OnboardingStarted,
    OnboardingStep,
)
from shared.py.analytics.catalog.settings import SettingsPreferencesChanged

pytestmark = pytest.mark.service

USER_OID = ObjectId("6acc0dac0cc0a00000000a11")
USER_ID = str(USER_OID)


@pytest.fixture(autouse=True)
async def _user(mongo_db) -> AsyncIterator[None]:
    await mongo_db["users"].delete_many({"_id": USER_OID})
    await mongo_db["users"].insert_one({"_id": USER_OID, "email": "steps-real@gaia.local"})
    await delete_cache(user_repository.cache_policy.entity_key(REPO_GLOBAL_SCOPE, USER_ID))
    yield
    await mongo_db["users"].delete_many({"_id": USER_OID})


@pytest.fixture
def captured() -> Iterator[MagicMock]:
    with (
        patch.object(onboarding_service, "capture") as capture,
        patch.object(
            onboarding_service, "spawn_background_task", side_effect=lambda coro, name: coro.close()
        ),
    ):
        yield capture


async def test_a_reloaded_start_fires_once(mongo_db, captured: MagicMock) -> None:
    first = await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.STARTED)
    again = await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.STARTED)

    assert (first, again) == (True, False)
    captured.assert_called_once()
    distinct_id, event, dedupe = captured.call_args.args
    assert distinct_id == UserId(USER_ID)
    assert event == OnboardingStarted()
    stored = (await mongo_db["users"].find_one({"_id": USER_OID}))["onboarding"]["steps_reached"]
    # Mongo keeps milliseconds: the stamp is the event's timestamp, to that precision.
    drift = stored["started"].replace(tzinfo=None) - dedupe.occurred_at.replace(tzinfo=None)
    assert abs(drift) < timedelta(milliseconds=1)


async def test_answers_save_stamps_questions_answered_not_a_settings_change(
    mongo_db, captured: MagicMock
) -> None:
    answers = OnboardingAnswers(
        profession="founder", needs=[OnboardingNeed.INBOX], other_need="invoices"
    )

    await onboarding_service.save_onboarding_answers(USER_ID, answers)
    await onboarding_service.save_onboarding_answers(USER_ID, answers)

    events = [c.args[1] for c in captured.call_args_list]
    assert events == [
        OnboardingPhaseCompleted(
            phase=OnboardingStep.QUESTIONS_ANSWERED, needs=["inbox"], has_other_need=True
        )
    ]
    assert not any(isinstance(e, SettingsPreferencesChanged) for e in events)
    onboarding = (await mongo_db["users"].find_one({"_id": USER_OID}))["onboarding"]
    assert onboarding["preferences"]["needs"] == ["inbox"]
    assert "questions_answered" in onboarding["steps_reached"]


async def test_a_reset_starts_a_new_run(mongo_db, captured: MagicMock) -> None:
    await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.PAYWALL_REACHED)
    await user_repository.reset_onboarding(USER_ID)

    assert await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.PAYWALL_REACHED)
    assert captured.call_count == 2
