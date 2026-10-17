"""Remix credit, the Sent with GAIA lookup, last week's time saved and the Monday card, on real Mongo.

Analytics is the patched seam; users, subscriptions, workflows, runs, rollups
and referrals are real rows.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.config.settings import settings
from app.constants.referrals import INVITE_PATH, ReferralNudge, ReferralSource
from app.constants.time_saved import MINUTES_SAVED_PER_ACTION, MINUTES_SAVED_PER_WORKFLOW_RUN
from app.db.mongodb.indexes import create_referral_indexes
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.usage_daily import UsageDailyIncrement, usage_daily_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.payment_models import SubscriptionDocument, SubscriptionStatus
from app.models.user_models import (
    OnboardingPreferences,
    OnboardingSubdocument,
    UserDocument,
)
from app.models.workflow_execution_models import (
    WorkflowExecutionDocument,
    WorkflowExecutionStatus,
)
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from app.services.referrals.attribution import ReferralAttribution, attribute_signup
from app.services.referrals.codes import ensure_code
from app.services.referrals.nudges import rendered_by_client, send_pitch
from app.services.referrals.sent_with_gaia import sent_with_gaia_link
from app.services.referrals.weekly_card import claim_weekly_card
from app.services.referrals.workflow_credit import workflow_creator_code
from app.services.time_saved import get_time_saved

pytestmark = pytest.mark.service

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)  # a Monday
LOOP_COLLECTIONS = (
    "referral_codes",
    "referrals",
    "subscriptions",
    "workflows",
    "workflow_executions",
    "usage_daily",
    "referral_nudges",
)


@pytest.fixture
async def clean(mongo_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LOOP_COLLECTIONS:
        await mongo_db.drop_collection(name)
    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", lambda name: mongo_db[name])
    await create_referral_indexes()


@pytest.fixture
def attributed(clean: None, real_redis: Any) -> Iterator[MagicMock]:
    with patch("app.services.referrals.attribution.capture") as capture:
        yield capture


async def _user(first_name: str, *, sent_with_gaia: bool | None = None) -> UserDocument:
    return await user_repository.create(
        UserDocument(
            name=f"{first_name} Test",
            first_name=first_name,
            email=f"{first_name.lower()}.{uuid.uuid4().hex[:8]}@example.com",
            onboarding=OnboardingSubdocument(
                preferences=OnboardingPreferences(sent_with_gaia=sent_with_gaia)
            ),
        )
    )


async def _subscribe(user: UserDocument) -> None:
    await subscription_repository.create(
        SubscriptionDocument(
            dodo_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
            user_id=user.id,
            product_id="pdt_pro_monthly",
            status=SubscriptionStatus.ACTIVE.value,
            created_at=NOW,
            updated_at=NOW,
        )
    )


async def _workflow(creator: UserDocument, **overrides: object) -> str:
    workflow = await workflow_repository.create(
        WorkflowDocument.model_validate(
            {
                "user_id": creator.id,
                "created_by": creator.id,
                "title": "Morning digest",
                "steps": [],
                "trigger_config": TriggerConfig(type=TriggerType.MANUAL),
                "is_public": True,
                **overrides,
            }
        )
    )
    return workflow.id


class TestWorkflowCredit:
    async def test_a_subscribed_creator_gets_the_signup(self, attributed: MagicMock) -> None:
        creator, visitor = await _user("Aryan"), await _user("Priya")
        await _subscribe(creator)

        code = await workflow_creator_code(await _workflow(creator))
        assert code == await ensure_code(creator)
        await attribute_signup(
            visitor.id, ReferralAttribution(code=code, source=ReferralSource.WORKFLOW)
        )

        referral = await referral_repository.get(visitor.id)
        assert referral.referrer_user_id == creator.id
        assert referral.source is ReferralSource.WORKFLOW
        assert attributed.call_args.args[1].source == "workflow"

    async def test_a_creator_without_a_subscription_credits_nobody(self, clean: None) -> None:
        creator = await _user("Aryan")
        assert await workflow_creator_code(await _workflow(creator)) is None

    @pytest.mark.parametrize(
        "overrides", [{"is_explore": True}, {"is_public": False}, {"created_by": None}]
    )
    async def test_only_a_creators_public_community_workflow_credits(
        self, clean: None, overrides: dict[str, object]
    ) -> None:
        creator = await _user("Aryan")
        await _subscribe(creator)
        assert await workflow_creator_code(await _workflow(creator, **overrides)) is None

    async def test_an_unknown_workflow_credits_nobody(self, clean: None) -> None:
        assert await workflow_creator_code("wf_missing") is None


class TestSentWithGaiaLink:
    async def test_on_and_subscribed_signs_with_the_invite_link(self, clean: None) -> None:
        user = await _user("Aryan", sent_with_gaia=True)
        await _subscribe(user)

        link = await sent_with_gaia_link(user.id)

        assert link == f"{settings.FRONTEND_URL}{INVITE_PATH}{await ensure_code(user)}"

    @pytest.mark.parametrize("sent_with_gaia", [None, False])
    async def test_off_by_default_and_when_turned_off(
        self, clean: None, sent_with_gaia: bool | None
    ) -> None:
        user = await _user("Aryan", sent_with_gaia=sent_with_gaia)
        await _subscribe(user)
        assert await sent_with_gaia_link(user.id) is None

    async def test_no_subscription_means_no_link_to_sign_with(self, clean: None) -> None:
        user = await _user("Aryan", sent_with_gaia=True)
        assert await sent_with_gaia_link(user.id) is None


async def _run(user_id: str, started_at: datetime, status: WorkflowExecutionStatus) -> None:
    await workflow_executions_repository.create(
        WorkflowExecutionDocument(
            execution_id=f"exe_{uuid.uuid4().hex[:8]}",
            workflow_id="wf_1",
            user_id=user_id,
            status=status,
            started_at=started_at,
        )
    )


class TestTimeSaved:
    async def test_counts_only_the_seven_full_days_before_today(self, clean: None) -> None:
        user_id = (await _user("Aryan")).id
        today = NOW.replace(hour=0)
        for day, count in [
            (today - timedelta(days=8), 50),  # before the window
            (today - timedelta(days=7), 4),  # first day in
            (today - timedelta(days=1), 6),  # last day in
            (today, 100),  # today is next week's
        ]:
            await usage_daily_repository.increment(
                user_id, day.date().isoformat(), UsageDailyIncrement(count=count)
            )
        await _run(user_id, today - timedelta(days=3), "success")
        await _run(user_id, today - timedelta(days=2), "failed")
        await _run(user_id, today - timedelta(days=9), "success")
        await _run(user_id, today + timedelta(hours=1), "success")
        await _run((await _user("Other")).id, today - timedelta(days=2), "success")

        summary = await get_time_saved(user_id, NOW.date())

        assert (summary.actions, summary.workflow_runs) == (10, 1)
        assert summary.minutes_saved == (
            10 * MINUTES_SAVED_PER_ACTION + 1 * MINUTES_SAVED_PER_WORKFLOW_RUN
        )
        assert summary.window_start == today - timedelta(days=7)
        assert summary.window_end == today

    async def test_a_quiet_week_saves_nothing(self, clean: None) -> None:
        summary = await get_time_saved((await _user("Aryan")).id, NOW.date())
        assert (summary.actions, summary.workflow_runs, summary.minutes_saved) == (0, 0, 0)


class TestWeeklyCard:
    """The Monday card draws on the same weekly nudge slot as every other referral pitch."""

    @pytest.fixture
    def nudge_capture(self, clean: None, real_redis: Any) -> Iterator[MagicMock]:
        with patch("app.services.referrals.nudges.capture") as capture:
            yield capture

    async def _busy_user(self) -> UserDocument:
        user = await _user("Aryan")
        await _subscribe(user)
        await usage_daily_repository.increment(
            user.id, (NOW - timedelta(days=2)).date().isoformat(), UsageDailyIncrement(count=12)
        )
        return user

    async def test_monday_shows_it_once_and_the_slot_is_then_spent(
        self, nudge_capture: MagicMock
    ) -> None:
        user = await self._busy_user()

        first = await claim_weekly_card(user.id, NOW)
        again = await claim_weekly_card(user.id, NOW + timedelta(hours=1))

        assert first.show is True and again.show is False
        assert first.stats.minutes_saved == 12 * MINUTES_SAVED_PER_ACTION
        assert first.share_link.endswith(f"{INVITE_PATH}{first.code}")
        assert nudge_capture.call_count == 1

    async def test_another_pitch_this_week_holds_the_card_back(
        self, nudge_capture: MagicMock
    ) -> None:
        user = await self._busy_user()
        assert await send_pitch(user.id, ReferralNudge.CHAT_CARD, rendered_by_client) is True

        assert (await claim_weekly_card(user.id, NOW)).show is False

    async def test_off_monday_the_slot_is_never_touched(self, nudge_capture: MagicMock) -> None:
        user = await self._busy_user()

        tuesday = await claim_weekly_card(user.id, NOW + timedelta(days=1))

        assert tuesday.show is False
        assert await send_pitch(user.id, ReferralNudge.CHAT_CARD, rendered_by_client) is True
