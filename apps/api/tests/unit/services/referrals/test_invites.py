"""Invite emails: each address judged on its own, sent through Gmail or GAIA's domain, opted out by link."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from fakeredis.aioredis import FakeRedis
import pytest
import time_machine

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.referrals import (
    INVITE_BATCH_MAX,
    INVITE_CEILING_FIX,
    INVITE_CEILING_MESSAGE,
    INVITE_CEILING_WHY,
    INVITE_DAILY_SEND_CEILING,
    INVITE_NO_SENDER_EMAIL_MESSAGE,
    INVITE_NO_SENDER_EMAIL_WHY,
    INVITE_PROVIDER_REFUSED_WHY,
    INVITE_QUOTA_KEY_TEMPLATE,
    INVITE_SEND_FAILED_FIX,
    INVITE_SEND_FAILED_MESSAGE,
    INVITE_SEND_FAILED_WHY,
)
from app.models.referral_models import (
    ReferralInviteChannel,
    ReferralInviteDocument,
    ReferralInviteStatus,
    ReferralInviteSurface,
)
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralInviteRequest
from app.services.email import ReferralInviteEmail
from app.services.mail.mail_service import EmailContent
from app.services.referrals.codes import share_link
from app.services.referrals.invites import (
    friend_price_line,
    price_lines,
    send_invites,
    unsubscribe_invite_recipient,
)
from app.services.referrals.offer import build_offer
from app.utils.errors import AppError
from app.utils.notification.unsubscribe import (
    UnsubscribeScope,
    build_invite_unsubscribe_url,
    sign_unsubscribe_token,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralInviteSent
from tests.factories import make_pro_plans

INVITES = "app.services.referrals.invites"
NOW = datetime(2026, 10, 14, 15, 45, 37, 123456, tzinfo=UTC)
SENDER = UserDocument(
    id="64a0000000000000000000a1",
    first_name="Aryan",
    email="aryan@example.com",
    picture="https://p/aryan.png",
)
QUOTA_KEY = INVITE_QUOTA_KEY_TEMPLATE.format(user_id=SENDER.id, day="2026-10-14")
CODE = "aryan-k7f2"
INTRO = "$15/month for your first 2 months"
REGULAR = "$30/month"


@dataclass
class Seams:
    load_user: AsyncMock
    suppressed_among: AsyncMock
    quota: FakeRedis
    claim: AsyncMock
    release: AsyncMock
    gmail_connected: AsyncMock
    ensure_code: AsyncMock
    send_gaia: AsyncMock
    send_gmail: AsyncMock
    capture: MagicMock
    log: MagicMock


@pytest.fixture
def seams(fake_redis: FakeRedis) -> Iterator[Seams]:
    with (
        time_machine.travel(NOW, tick=False),
        patch(f"{INVITES}.load_user", AsyncMock(return_value=SENDER)) as load_user,
        patch(
            f"{INVITES}.email_suppression_repository.suppressed_among",
            AsyncMock(return_value=set()),
        ) as suppressed_among,
        patch(
            f"{INVITES}.referral_invite_repository.claim",
            AsyncMock(
                side_effect=lambda doc: doc.model_copy(
                    update={"id": f"claim-{doc.recipient_email}"}
                )
            ),
        ) as claim,
        patch(f"{INVITES}.referral_invite_repository.release", AsyncMock()) as release,
        patch(f"{INVITES}.check_integration_status", AsyncMock(return_value=False)) as gmail,
        patch(f"{INVITES}.ensure_code", AsyncMock(return_value=CODE)) as ensure_code,
        patch(f"{INVITES}.payment_service.get_pro_plans", AsyncMock(return_value=make_pro_plans())),
        patch(f"{INVITES}.send_referral_invite_email", AsyncMock()) as send_gaia,
        patch(
            f"{INVITES}.send_email",
            AsyncMock(return_value=SimpleNamespace(successful=True, error=None)),
        ) as send_gmail,
        patch(f"{INVITES}.capture") as capture,
        patch(f"{INVITES}.log") as log,
    ):
        yield Seams(
            load_user,
            suppressed_among,
            fake_redis,
            claim,
            release,
            gmail,
            ensure_code,
            send_gaia,
            send_gmail,
            capture,
            log,
        )


def _request(*emails: str) -> ReferralInviteRequest:
    return ReferralInviteRequest(emails=list(emails), surface=ReferralInviteSurface.PAGE)


def _statuses(response) -> list[tuple[str, ReferralInviteStatus]]:
    return [(r.email, r.status) for r in response.results]


def test_the_price_lines_read_off_the_live_offer() -> None:
    assert price_lines(build_offer(make_pro_plans())) == (INTRO, REGULAR)


def test_the_referrers_line_about_a_friend_reads_off_the_live_offer() -> None:
    assert friend_price_line(build_offer(make_pro_plans())) == "$15/month for their first 2 months"


class TestUnsubscribe:
    async def test_a_signed_link_suppresses_its_address_for_every_sender(self) -> None:
        token = sign_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, "priya@example.com")
        with patch(f"{INVITES}.email_suppression_repository.suppress", AsyncMock()) as suppress:
            assert await unsubscribe_invite_recipient(token) is True

        suppress.assert_awaited_once_with("priya@example.com")

    async def test_a_forged_or_lifecycle_link_suppresses_nobody(self) -> None:
        lifecycle = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, "priya@example.com")
        with patch(f"{INVITES}.email_suppression_repository.suppress", AsyncMock()) as suppress:
            assert await unsubscribe_invite_recipient(lifecycle) is False
            assert await unsubscribe_invite_recipient("forged") is False

        suppress.assert_not_awaited()


class TestEachAddressIsJudgedOnItsOwn:
    async def test_every_address_gets_its_own_status_in_request_order(self, seams: Seams) -> None:
        seams.suppressed_among.return_value = {"opted@example.com"}
        claim = seams.claim.side_effect
        seams.claim.side_effect = lambda doc: (
            None if doc.recipient_email == "known@example.com" else claim(doc)
        )

        response = await send_invites(
            SENDER.id,
            _request(
                "not-an-email",
                " Aryan+alt@Example.com ",
                "opted@example.com",
                "known@example.com",
                " Priya@Example.com ",
            ),
        )

        assert _statuses(response) == [
            ("not-an-email", ReferralInviteStatus.INVALID),
            (" Aryan+alt@Example.com ", ReferralInviteStatus.OWN_ADDRESS),
            ("opted@example.com", ReferralInviteStatus.UNSUBSCRIBED),
            ("known@example.com", ReferralInviteStatus.ALREADY_INVITED),
            (" Priya@Example.com ", ReferralInviteStatus.SENT),
        ]
        seams.load_user.assert_awaited_once_with(SENDER.id)
        seams.suppressed_among.assert_awaited_once_with(
            ["aryan@example.com", "opted@example.com", "known@example.com", "priya@example.com"]
        )
        assert await seams.quota.get(QUOTA_KEY) == "1"
        assert [c.args[0].recipient_email for c in seams.claim.await_args_list] == [
            "known@example.com",
            "priya@example.com",
        ]
        seams.log.set_ns.assert_called_once_with(
            "referral", invite_channel="gaia", invites_requested=5, invites_sent=1
        )

    async def test_a_sender_without_an_email_cannot_invite(self, seams: Seams) -> None:
        seams.load_user.return_value = SENDER.model_copy(update={"email": None})

        with pytest.raises(AppError) as refused:
            await send_invites(SENDER.id, _request("priya@example.com"))

        assert refused.value.status_code == 409
        assert refused.value.to_dict() == {
            "message": INVITE_NO_SENDER_EMAIL_MESSAGE,
            "why": INVITE_NO_SENDER_EMAIL_WHY,
            "user_id": SENDER.id,
        }
        seams.claim.assert_not_awaited()


class TestTheDailyCeiling:
    async def test_a_batch_reaching_exactly_the_ceiling_is_sent(self, seams: Seams) -> None:
        await seams.quota.set(QUOTA_KEY, INVITE_DAILY_SEND_CEILING - 1)

        response = await send_invites(SENDER.id, _request("priya@example.com"))

        assert _statuses(response) == [("priya@example.com", ReferralInviteStatus.SENT)]

    async def test_the_allowance_is_counted_on_the_utc_day_not_the_local_one(
        self, seams: Seams
    ) -> None:
        # 20:00 UTC is already the next morning in Kolkata.
        with time_machine.travel(
            datetime(2026, 10, 15, 1, 30, tzinfo=ZoneInfo("Asia/Kolkata")), tick=False
        ):
            await send_invites(SENDER.id, _request("priya@example.com"))

        utc_day = INVITE_QUOTA_KEY_TEMPLATE.format(user_id=SENDER.id, day="2026-10-14")
        assert await seams.quota.get(utc_day) == "1"

    async def test_a_batch_past_the_ceiling_sends_nothing(self, seams: Seams) -> None:
        await seams.quota.set(QUOTA_KEY, INVITE_DAILY_SEND_CEILING - 1)

        with pytest.raises(AppError) as refused:
            await send_invites(SENDER.id, _request("priya@example.com", "sam@example.com"))

        assert refused.value.status_code == 429
        assert refused.value.to_dict() == {
            "message": INVITE_CEILING_MESSAGE,
            "why": INVITE_CEILING_WHY,
            "fix": INVITE_CEILING_FIX,
            "sent_today": INVITE_DAILY_SEND_CEILING - 1,
            "ceiling": INVITE_DAILY_SEND_CEILING,
        }
        seams.claim.assert_not_awaited()

    async def test_the_senders_own_and_opted_out_addresses_do_not_count(self, seams: Seams) -> None:
        await seams.quota.set(QUOTA_KEY, INVITE_DAILY_SEND_CEILING - 1)
        seams.suppressed_among.return_value = {"opted@example.com"}

        response = await send_invites(
            SENDER.id, _request("aryan@example.com", "opted@example.com", "priya@example.com")
        )

        assert _statuses(response)[-1] == ("priya@example.com", ReferralInviteStatus.SENT)

    async def test_concurrent_batches_never_send_past_the_ceiling_together(
        self, seams: Seams
    ) -> None:
        async def connected_after_a_yield(*_: object) -> bool:
            await asyncio.sleep(0)
            return False

        seams.gmail_connected.side_effect = connected_after_a_yield
        batches = [
            _request(*(f"friend{b}-{i}@example.com" for i in range(INVITE_BATCH_MAX)))
            for b in range(5)
        ]

        outcomes = await asyncio.gather(
            *(send_invites(SENDER.id, batch) for batch in batches), return_exceptions=True
        )

        sent = sum(
            r.status is ReferralInviteStatus.SENT
            for outcome in outcomes
            if not isinstance(outcome, BaseException)
            for r in outcome.results
        )
        assert sent == INVITE_DAILY_SEND_CEILING
        refused = [o for o in outcomes if isinstance(o, AppError)]
        assert [o.status_code for o in refused] == [429]


class TestFromGaiasDomain:
    async def test_without_gmail_the_invite_leaves_gaias_domain_under_the_senders_name(
        self, seams: Seams
    ) -> None:
        await send_invites(SENDER.id, _request(" Priya@Example.com "))

        seams.gmail_connected.assert_awaited_once_with(GMAIL_INTEGRATION_ID, SENDER.id)
        seams.ensure_code.assert_awaited_once_with(SENDER)
        seams.send_gaia.assert_awaited_once_with(
            ReferralInviteEmail(
                to="priya@example.com",
                referrer_name="Aryan",
                referrer_email="aryan@example.com",
                referrer_picture="https://p/aryan.png",
                price_line=INTRO,
                regular_price_line=REGULAR,
                invite_link=share_link(CODE),
                unsubscribe_url=build_invite_unsubscribe_url("priya@example.com"),
            )
        )
        seams.send_gmail.assert_not_awaited()
        seams.claim.assert_awaited_once_with(
            ReferralInviteDocument(
                sender_user_id=SENDER.id,
                recipient_email="priya@example.com",
                surface=ReferralInviteSurface.PAGE,
                channel=ReferralInviteChannel.GAIA,
                sent_at=NOW,
            )
        )
        seams.capture.assert_called_once_with(
            UserId(SENDER.id), ReferralInviteSent(invite_surface="page", channel="gaia")
        )

    async def test_a_sender_without_a_first_name_signs_with_their_address(
        self, seams: Seams
    ) -> None:
        seams.load_user.return_value = SENDER.model_copy(update={"first_name": None})

        await send_invites(SENDER.id, _request("priya@example.com"))

        assert seams.send_gaia.await_args.args[0].referrer_name == "aryan@example.com"

    async def test_a_failed_send_frees_the_address_and_fails_loudly(self, seams: Seams) -> None:
        seams.send_gaia.side_effect = ConnectionError("smtp down")

        with pytest.raises(AppError) as failed:
            await send_invites(SENDER.id, _request("priya@example.com"))

        assert failed.value.status_code == 502
        assert failed.value.to_dict() == {
            "message": INVITE_SEND_FAILED_MESSAGE,
            "why": INVITE_PROVIDER_REFUSED_WHY,
            "channel": "gaia",
            "error_type": "ConnectionError",
        }
        assert isinstance(failed.value.__cause__, ConnectionError)
        seams.release.assert_awaited_once_with("claim-priya@example.com")
        seams.capture.assert_not_called()
        assert await seams.quota.get(QUOTA_KEY) == "0"


class TestFromTheSendersGmail:
    async def test_with_gmail_connected_the_invite_leaves_the_senders_own_mailbox(
        self, seams: Seams
    ) -> None:
        seams.gmail_connected.return_value = True

        await send_invites(SENDER.id, _request("Priya@Example.com"))

        seams.send_gmail.assert_awaited_once_with(
            SENDER.id,
            "priya@example.com",
            EmailContent(
                subject="Aryan sent you a gift!",
                body=(
                    "Hey! I've been using GAIA and it's honestly made my days lighter. "
                    f"Here's GAIA for {INTRO} 💛\n\n{share_link(CODE)}\n\nAryan\n\n"
                    "Don't want invites like this? "
                    f"{build_invite_unsubscribe_url('priya@example.com')}"
                ),
            ),
        )
        seams.send_gaia.assert_not_awaited()
        assert seams.claim.await_args.args[0].channel is ReferralInviteChannel.GMAIL
        seams.capture.assert_called_once_with(
            UserId(SENDER.id), ReferralInviteSent(invite_surface="page", channel="gmail")
        )
        seams.log.set_ns.assert_called_once_with(
            "referral", invite_channel="gmail", invites_requested=1, invites_sent=1
        )

    async def test_gmail_refusing_the_message_frees_the_address_and_says_reconnect(
        self, seams: Seams
    ) -> None:
        seams.gmail_connected.return_value = True
        seams.send_gmail.return_value = SimpleNamespace(successful=False, error="quota")

        with pytest.raises(AppError) as failed:
            await send_invites(SENDER.id, _request("priya@example.com"))

        assert failed.value.status_code == 502
        assert failed.value.to_dict() == {
            "message": INVITE_SEND_FAILED_MESSAGE,
            "why": INVITE_SEND_FAILED_WHY,
            "fix": INVITE_SEND_FAILED_FIX,
            "provider_error": "quota",
        }
        seams.release.assert_awaited_once_with("claim-priya@example.com")
        seams.capture.assert_not_called()
