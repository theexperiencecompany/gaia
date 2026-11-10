"""Linking a bot account as the user experiences it: tap, link, greeting handed to the outbox.

Unit tests prove each half with the other mocked, and the only e2e mentioning the
flow asserts an instruction string. Nothing proved the shared tail every link route
owes: write the link, hand the first contact (or the greeting when there is none)
to the outbox, sync the account FS, attribute the funnel event — and spend nothing
when the link is refused. The outbox's own delivery of both is proved in
test_outbox_timeline (I1).

Real: complete_platform_link and the report it builds. Doubled: the DB write
(link_account), the outbox intake (submit), account sync, analytics.
Also real here: publish_outbound_message (destination resolution + envelope).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.platform_models import PlatformLinkResult
from app.services.outbox.models import NoticeReport
from app.services.outbox.prerendered import PrerenderedKind
from app.services.outbox.transport.bot_queue import OutboundResult, publish_outbound_message
from app.services.platform_link_completion import PostLinkSideEffectError, complete_platform_link
from app.services.platform_link_service import PlatformAccountTakenError, PlatformLinkService
from app.utils.errors import AppError

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("onboarding_finish_on_link")]

COMPLETION = "app.services.platform_link_completion"

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
PLATFORM_USER_ID = "tg-123"


def _link_result(*, is_new_link: bool = True, platform: str = "telegram") -> PlatformLinkResult:
    return PlatformLinkResult(
        status="linked",
        platform=platform,
        platform_user_id=PLATFORM_USER_ID,
        connected_at=datetime.now(UTC).isoformat(),
        is_new_link=is_new_link,
    )


def _submitted(submit: AsyncMock) -> NoticeReport:
    submit.assert_awaited_once()
    report = submit.await_args.args[0]
    assert isinstance(report, NoticeReport)
    return report


class TestOneTapLinkDeliversFirstContact:
    async def test_first_contact_is_submitted_to_the_telegram_dm_instead_of_the_greeting(
        self,
    ) -> None:
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(f"{COMPLETION}.submit", new=AsyncMock()) as submit,
            patch(f"{COMPLETION}.schedule_account_sync") as sync,
            patch(f"{COMPLETION}.capture") as capture,
        ):
            completion = await complete_platform_link(
                USER_ID, "telegram", PLATFORM_USER_ID, first_contact=["Welcome!"]
            )

        assert completion.first_contact_delivered is True
        report = _submitted(submit)
        assert report.prerendered is not None
        assert report.prerendered.kind is PrerenderedKind.FIRST_CONTACT
        assert report.prerendered.bubbles == ["Welcome!"]
        assert report.delivery_policy.channel is ConversationSource.TELEGRAM
        sync.assert_called_once_with(USER_ID)
        capture.assert_called_once()

    async def test_an_outbox_that_cannot_take_the_first_contact_fails_the_follow_through_loudly(
        self,
    ) -> None:
        """Submit raises when it cannot be durable: the caller spends its credential rather than retry into a duplicate."""
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(f"{COMPLETION}.submit", new=AsyncMock(side_effect=ConnectionError("redis down"))),
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture"),
            pytest.raises(PostLinkSideEffectError, match="redis down"),
        ):
            await complete_platform_link(
                USER_ID, "telegram", PLATFORM_USER_ID, first_contact=["Welcome!"]
            )


class TestFreshLinkWithoutFirstContactSendsGreeting:
    async def test_the_confirmation_is_submitted_for_the_new_account(self) -> None:
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(f"{COMPLETION}.submit", new=AsyncMock()) as submit,
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture"),
        ):
            completion = await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert completion.first_contact_delivered is True
        report = _submitted(submit)
        assert report.prerendered is not None
        assert report.prerendered.kind is PrerenderedKind.ACCOUNT_LINKED

    async def test_relink_sends_no_greeting_and_captures_nothing(self) -> None:
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=False)),
            ),
            patch(f"{COMPLETION}.submit", new=AsyncMock()) as submit,
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture") as capture,
        ):
            completion = await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert completion.first_contact_delivered is True
        submit.assert_not_awaited()
        capture.assert_not_called()


class TestRefusedLinkSpendsNothing:
    async def test_conflict_is_409_with_no_side_effects(self) -> None:
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(side_effect=PlatformAccountTakenError("already linked")),
            ),
            patch(f"{COMPLETION}.submit", new=AsyncMock()) as submit,
            patch(f"{COMPLETION}.capture") as capture,
        ):
            with pytest.raises(AppError) as exc_info:
                await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert exc_info.value.status_code == 409
        submit.assert_not_awaited()
        capture.assert_not_called()


class TestOutboundPublishResolvesAndEnvelopes:
    async def test_unlinked_account_skips_without_touching_the_broker(self) -> None:
        with (
            patch(
                "app.services.outbox.transport.bot_queue.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.outbox.transport.bot_queue.get_rabbitmq_publisher",
                new=AsyncMock(side_effect=AssertionError("broker must not be reached")),
            ),
        ):
            result = await publish_outbound_message(ConversationSource.TELEGRAM, USER_ID, ["hi"])

        assert result is OutboundResult.SKIPPED

    async def test_linked_account_publishes_one_ordered_envelope(self) -> None:
        sent: list[bytes] = []

        async def _capture(queue: str, body: bytes, **kwargs) -> None:
            sent.append(body)

        publisher = AsyncMock()
        publisher.publish_outbound = AsyncMock(side_effect=_capture)
        with (
            patch(
                "app.services.outbox.transport.bot_queue.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(return_value={"telegram": {"platformUserId": PLATFORM_USER_ID}}),
            ),
            patch(
                "app.services.outbox.transport.bot_queue.get_rabbitmq_publisher",
                new=AsyncMock(return_value=publisher),
            ),
        ):
            result = await publish_outbound_message(
                ConversationSource.TELEGRAM, USER_ID, ["hello there"]
            )

        assert result is OutboundResult.PUBLISHED
        assert len(sent) == 1
        envelope = json.loads(sent[0].decode())
        assert envelope["destination_id"] == PLATFORM_USER_ID
        assert "hello there" in json.dumps(envelope)
