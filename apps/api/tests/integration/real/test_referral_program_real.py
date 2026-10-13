"""Attribution at signup, the checkout gift and invite sending, against real Mongo.

Dodo, the two mail transports, the integration status and analytics are the
patched seams; codes, referrals, invites and suppressions are real rows.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.config.settings import settings
from app.db.mongodb.indexes import create_referral_indexes
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.referral_invites import referral_invite_repository
from app.db.repositories.referrals import referral_repository
from app.db.repositories.users import user_repository
from app.models.mail_models import GmailToolResult
from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.models.referral_models import (
    ReferralInviteStatus,
    ReferralInviteSurface,
    ReferredFriendStatus,
)
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralInviteRequest
from app.services.referrals.attribution import ReferralAttribution, attribute_signup
from app.services.referrals.codes import ensure_code
from app.services.referrals.gift import gift_code_for_checkout, pending_gift_referral
from app.services.referrals.invites import send_invites, unsubscribe_invite_recipient
from app.services.referrals.offer import ProPlans
from app.utils.errors import AppError
from app.utils.notification.unsubscribe import UnsubscribeScope, sign_unsubscribe_token

pytestmark = pytest.mark.service

NOW = datetime(2026, 10, 14, tzinfo=UTC)
REFERRAL_COLLECTIONS = ("referral_codes", "referrals", "referral_invites", "email_suppressions")


def _plan(duration: PlanDuration, amount: int) -> PlanResponse:
    return PlanResponse(
        id=f"plan_{duration.value}",
        dodo_product_id=f"pdt_pro_{duration.value}",
        name="Pro",
        plan_type=PlanTier.PRO,
        amount=amount,
        currency="USD",
        duration=duration,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


PLANS = ProPlans(
    monthly=_plan(PlanDuration.MONTHLY, 3000), yearly=_plan(PlanDuration.YEARLY, 27000)
)


@dataclass
class FakeDiscounts:
    created: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def discounts(self) -> "FakeDiscounts":
        return self

    def create(self, **params: Any) -> SimpleNamespace:
        self.created.append(params)
        n = len(self.created)
        return SimpleNamespace(code=f"GIFT{n}", discount_id=f"dsc_{n}")

    def delete(self, discount_id: str) -> None:
        self.deleted.append(discount_id)


async def _user(first_name: str, email: str | None = None) -> UserDocument:
    return await user_repository.create(
        UserDocument(
            name=f"{first_name} Test",
            first_name=first_name,
            email=email or f"{first_name.lower()}.{uuid.uuid4().hex[:8]}@example.com",
        )
    )


@pytest.fixture
async def referral_indexes(mongo_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Create the production indexes: the once-only guarantees live in them, not in the code."""
    for name in REFERRAL_COLLECTIONS:
        await mongo_db.drop_collection(name)
    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", lambda name: mongo_db[name])
    await create_referral_indexes()


@pytest.fixture
def analytics(referral_indexes: None, real_redis: Any) -> Iterator[MagicMock]:
    with (
        patch("app.services.referrals.attribution.capture") as attributed,
        patch("app.services.referrals.invites.capture"),
    ):
        yield attributed


class TestAttribution:
    async def test_a_new_user_joins_their_referrers_friends(self, analytics: MagicMock) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        code = await ensure_code(referrer)

        await attribute_signup(friend.id, ReferralAttribution(code=code))

        referral = await referral_repository.get(friend.id)
        assert referral.referrer_user_id == referrer.id
        assert referral.status is ReferredFriendStatus.JOINED
        assert analytics.call_args.args[1].referrer_id == referrer.id

    async def test_the_same_mailbox_under_another_spelling_is_not_a_friend(
        self, analytics: MagicMock
    ) -> None:
        local = uuid.uuid4().hex[:10]
        referrer = await _user("Aryan", f"{local}@gmail.com")
        alt = await _user("Alt", f"{local[:4]}.{local[4:]}+ref@googlemail.com")

        await attribute_signup(alt.id, ReferralAttribution(code=await ensure_code(referrer)))

        assert await referral_repository.get(alt.id) is None
        analytics.assert_not_called()

    async def test_an_unknown_code_attributes_nothing(self, analytics: MagicMock) -> None:
        friend = await _user("Priya")
        await attribute_signup(friend.id, ReferralAttribution(code="nobody-zzzz"))
        assert await referral_repository.get(friend.id) is None

    async def test_a_users_code_is_minted_once(self, analytics: MagicMock) -> None:
        referrer = await _user("Aryan")
        first = await ensure_code(referrer)
        assert await ensure_code(referrer) == first
        assert first.startswith("aryan-")
        assert (await referral_code_repository.get_by_code(first)).user_id == referrer.id


class TestCheckoutGift:
    async def test_a_referred_friend_gets_one_single_use_code_per_cycle(
        self, analytics: MagicMock
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        await attribute_signup(friend.id, ReferralAttribution(code=await ensure_code(referrer)))
        dodo = FakeDiscounts()

        referral = await pending_gift_referral(friend.id)
        monthly = await gift_code_for_checkout(dodo, referral, "pdt_pro_monthly", PLANS)
        again = await gift_code_for_checkout(
            dodo, await pending_gift_referral(friend.id), "pdt_pro_monthly", PLANS
        )
        yearly = await gift_code_for_checkout(dodo, referral, "pdt_pro_yearly", PLANS)

        assert monthly == again == "GIFT1" and yearly == "GIFT2"
        assert [
            (c["amount"], c["subscription_cycles"], c["usage_limit"]) for c in dodo.created
        ] == [
            (5000, 2, 1),
            (1111, 1, 1),
        ]
        assert dodo.created[0]["restricted_to"] == ["pdt_pro_monthly"]

    async def test_no_gift_off_the_pro_plans_or_once_the_friend_has_paid(
        self, analytics: MagicMock
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        await attribute_signup(friend.id, ReferralAttribution(code=await ensure_code(referrer)))
        dodo = FakeDiscounts()

        referral = await pending_gift_referral(friend.id)
        assert await gift_code_for_checkout(dodo, referral, "pdt_max_monthly", PLANS) is None

        await referral_repository.mark_paid(friend.id, payment_id="pay_1", paid_at=NOW)
        assert await pending_gift_referral(friend.id) is None
        assert await pending_gift_referral((await _user("Stranger")).id) is None
        assert dodo.created == []


@dataclass
class MailSeams:
    gaia: AsyncMock
    gmail: AsyncMock


@pytest.fixture
def mail(analytics: MagicMock) -> Iterator[MailSeams]:
    with (
        patch("app.services.referrals.invites.send_referral_invite_email", AsyncMock()) as gaia,
        patch(
            "app.services.referrals.invites.send_email",
            AsyncMock(return_value=GmailToolResult(successful=True)),
        ) as gmail,
        patch(
            "app.services.referrals.invites.check_integration_status", AsyncMock(return_value=False)
        ),
        patch(
            "app.services.referrals.invites.payment_service.get_pro_plans",
            AsyncMock(return_value=PLANS),
        ),
        patch.object(settings, "EMAIL_UNSUBSCRIBE_SECRET", "test-secret"),
    ):
        yield MailSeams(gaia, gmail)


class TestInvites:
    async def test_each_address_gets_its_own_status(self, mail: MailSeams) -> None:
        sender = await _user("Aryan")
        friend = f"friend-{uuid.uuid4().hex[:8]}@example.com"
        opted_out = f"gone-{uuid.uuid4().hex[:8]}@example.com"
        assert await unsubscribe_invite_recipient(
            sign_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, opted_out)
        )

        response = await send_invites(
            sender.id,
            ReferralInviteRequest(
                emails=[friend, "not-an-email", sender.email.upper(), opted_out, friend],
                surface=ReferralInviteSurface.PAGE,
            ),
        )

        assert [r.status for r in response.results] == [
            ReferralInviteStatus.SENT,
            ReferralInviteStatus.INVALID,
            ReferralInviteStatus.OWN_ADDRESS,
            ReferralInviteStatus.UNSUBSCRIBED,
            ReferralInviteStatus.ALREADY_INVITED,
        ]
        assert [r.email for r in response.results][1] == "not-an-email"
        sent = mail.gaia.call_args.args[0]
        assert sent.to == friend and sent.referrer_email == sender.email
        assert sent.price_line == "$15/month for your first 2 months"
        assert sent.invite_link.endswith(f"/invite/{await ensure_code(sender)}")
        mail.gmail.assert_not_called()

    async def test_a_friend_invited_before_shows_as_invited(self, mail: MailSeams) -> None:
        sender = await _user("Aryan")
        friend = f"friend-{uuid.uuid4().hex[:8]}@example.com"
        request = ReferralInviteRequest(emails=[friend], surface=ReferralInviteSurface.HOVER_CARD)

        await send_invites(sender.id, request)
        again = await send_invites(sender.id, request)

        assert again.results[0].status is ReferralInviteStatus.ALREADY_INVITED
        assert mail.gaia.await_count == 1

    async def test_a_failed_send_raises_and_frees_the_address_for_a_retry(
        self, mail: MailSeams
    ) -> None:
        sender = await _user("Aryan")
        friend = f"friend-{uuid.uuid4().hex[:8]}@example.com"
        request = ReferralInviteRequest(emails=[friend], surface=ReferralInviteSurface.PAGE)
        mail.gaia.side_effect = [RuntimeError("resend down"), None]

        with pytest.raises(AppError) as refused:
            await send_invites(sender.id, request)
        assert refused.value.status_code == 502
        assert await referral_invite_repository.invited_by(sender.id) == set()

        assert (await send_invites(sender.id, request)).results[
            0
        ].status is ReferralInviteStatus.SENT

    async def test_a_connected_gmail_sends_from_the_users_own_mailbox(
        self, mail: MailSeams
    ) -> None:
        sender = await _user("Aryan")
        friend = f"friend-{uuid.uuid4().hex[:8]}@example.com"
        with patch(
            "app.services.referrals.invites.check_integration_status", AsyncMock(return_value=True)
        ):
            await send_invites(
                sender.id,
                ReferralInviteRequest(emails=[friend], surface=ReferralInviteSurface.AGENT),
            )

        user_id, to, content = mail.gmail.call_args.args
        assert (user_id, to) == (sender.id, friend)
        assert "$15/month for your first 2 months" in content.body
        assert "/api/v1/referrals/unsubscribe/" in content.body
        mail.gaia.assert_not_called()

    async def test_a_forged_unsubscribe_token_suppresses_nobody(self, mail: MailSeams) -> None:
        assert await unsubscribe_invite_recipient("forged") is False
        notification_token = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, "x@example.com")
        assert await unsubscribe_invite_recipient(notification_token) is False
