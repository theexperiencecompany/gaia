"""Onboarding wizard steps against REAL MongoDB: each step's event fires once per onboarding run.

The step gate is a conditional $set on users.onboarding.steps_reached, so only a
real Mongo proves a replayed report cannot fire twice. PostHog is the one
substituted seam.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.redis import delete_cache
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.user_models import OnboardingAnswers, OnboardingNeed, OnboardingRequest
from app.services.onboarding import onboarding_service
from app.services.platform_link_service import PlatformLinkService
from shared.py.analytics import UserId
from shared.py.analytics.catalog.onboarding import (
    OnboardingCompleted,
    OnboardingPhaseCompleted,
    OnboardingStarted,
    OnboardingStep,
)
from shared.py.analytics.catalog.settings import SettingsPreferencesChanged
from tests.helpers import stored_conversation

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
        profession="founder", needs=[OnboardingNeed.INBOX], other_need="invoices", language="de-DE"
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
    assert onboarding["preferences"]["language"] == "de"
    assert "questions_answered" in onboarding["steps_reached"]


async def test_a_reset_starts_a_new_run(mongo_db, captured: MagicMock) -> None:
    await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.PAYWALL_REACHED)
    await user_repository.reset_onboarding(USER_ID)

    assert await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.PAYWALL_REACHED)
    assert captured.call_count == 2


async def test_the_bot_link_landing_finishes_onboarding_once(mongo_db, captured: MagicMock) -> None:
    """A paid user who taps Start in Telegram and never returns to the web tab is not left unfinished."""
    await onboarding_service.save_onboarding_answers(
        USER_ID, OnboardingAnswers(profession="founder", needs=[OnboardingNeed.INBOX])
    )
    await onboarding_service.record_onboarding_step(USER_ID, OnboardingStep.PAID_REVEAL_SEEN)
    await PlatformLinkService.link_account(USER_ID, "telegram", "tg-steps-real")

    with patch.object(onboarding_service, "resolve_first_question", AsyncMock(return_value=None)):
        await onboarding_service.complete_onboarding_on_platform_link(USER_ID)
        await onboarding_service.complete_onboarding_on_platform_link(USER_ID)
        # The web tab's own submit, arriving later, replays into the same gate.
        await onboarding_service.complete_onboarding(
            USER_ID, OnboardingRequest(profession="founder", needs=[OnboardingNeed.INBOX])
        )

    onboarding = (await mongo_db["users"].find_one({"_id": USER_OID}))["onboarding"]
    assert onboarding["completed"] is True
    completions = [
        c.args[1] for c in captured.call_args_list if isinstance(c.args[1], OnboardingCompleted)
    ]
    assert [c.linked_platform for c in completions] == ["telegram"]
    seeded = await stored_conversation(
        mongo_db["conversations"], onboarding["getting_started_conversation_id"]
    )
    await conversation_repository.delete_all_for_user(USER_ID)
    assert seeded is not None
    assert "Telegram" in json.dumps(seeded["messages"], default=str)
