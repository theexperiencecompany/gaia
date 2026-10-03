"""Linking a bot account as the user experiences it: tap, link, greeting arrives.

Unit tests prove each half with the other mocked (link service with the
outbound publish patched out, outbound publish with the link lookup patched
out), and the only e2e mentioning the flow asserts an instruction string.
Nothing proved the shared tail every link route owes: write the link, deliver
the first contact (or the greeting when there is none), sync the account FS,
attribute the funnel event — and spend nothing when the link is refused.

Real: complete_platform_link, notify_account_linked,
publish_outbound_message (destination resolution + envelope). Doubled: the DB
write (link_account), the broker (fake publisher), account sync, analytics.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.platform_models import PlatformLinkResult
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.services.platform_link_completion import complete_platform_link
from app.services.platform_link_service import PlatformAccountTakenError, PlatformLinkService
from app.utils.errors import AppError

pytestmark = pytest.mark.e2e

COMPLETION = "app.services.platform_link_completion"
DELIVERY = "app.services.outbound_delivery"

USER_ID = "user-1"
PLATFORM_USER_ID = "tg-123"


def _link_result(*, is_new_link: bool = True) -> PlatformLinkResult:
    return PlatformLinkResult(
        status="linked",
        platform="telegram",
        platform_user_id=PLATFORM_USER_ID,
        connected_at=datetime.now(UTC).isoformat(),
        is_new_link=is_new_link,
    )


class TestOneTapLinkDeliversFirstContact:
    async def test_first_contact_goes_out_on_the_queue(self) -> None:
        """Only the DB write and the broker are doubled, so a broken queue name or lost destination fails."""
        sent: list[bytes] = []

        async def _capture(queue: str, body: bytes, **kwargs: Any) -> None:
            sent.append(body)

        publisher = AsyncMock()
        publisher.publish_outbound = AsyncMock(side_effect=_capture)
        with (
            patch.object(
                PlatformLinkService,
                "link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(
                "app.services.outbound_delivery.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(
                    return_value={"telegram": {"platformUserId": PLATFORM_USER_ID}}
                ),
            ),
            patch(
                "app.services.outbound_delivery.get_rabbitmq_publisher",
                new=AsyncMock(return_value=publisher),
            ),
            patch(f"{COMPLETION}.notify_account_linked", new=AsyncMock()) as notify,
            patch(f"{COMPLETION}.schedule_account_sync") as sync,
            patch(f"{COMPLETION}.capture_event") as capture,
        ):
            completion = await complete_platform_link(
                USER_ID, "telegram", PLATFORM_USER_ID, first_contact=["Welcome!"]
            )

        assert completion.first_contact_delivered is True
        assert len(sent) == 1
        envelope = json.loads(sent[0].decode())
        assert envelope["destination_id"] == PLATFORM_USER_ID
        assert "Welcome!" in json.dumps(envelope)
        # First contact replaces the greeting — never both.
        notify.assert_not_awaited()
        sync.assert_called_once_with(USER_ID)
        capture.assert_called_once()

    async def test_failed_first_contact_is_reported_not_retried(self) -> None:
        """The caller must learn the greeting failed: nothing retries the publish."""
        publish = AsyncMock(return_value=OutboundResult.FAILED)
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(f"{COMPLETION}.publish_outbound_message", new=publish),
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture_event"),
        ):
            completion = await complete_platform_link(
                USER_ID, "telegram", PLATFORM_USER_ID, first_contact=["Welcome!"]
            )

        # The link itself held; only the message was lost.
        assert completion.link.is_new_link is True
        assert completion.first_contact_delivered is False


class TestFreshLinkWithoutFirstContactSendsGreeting:
    async def test_greeting_reaches_the_new_account(self) -> None:
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=True)),
            ),
            patch(
                f"{COMPLETION}.publish_outbound_message",
                new=AsyncMock(side_effect=AssertionError("first contact path must not run")),
            ),
            patch(
                f"{DELIVERY}.publish_outbound_message",
                new=AsyncMock(return_value=OutboundResult.PUBLISHED),
            ) as greeting_publish,
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture_event"),
        ):
            completion = await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert completion.first_contact_delivered is True
        greeting_publish.assert_awaited_once()

    async def test_relink_sends_no_greeting_and_captures_nothing(self) -> None:
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.link_account",
                new=AsyncMock(return_value=_link_result(is_new_link=False)),
            ),
            patch(f"{COMPLETION}.notify_account_linked", new=AsyncMock()) as notify,
            patch(f"{COMPLETION}.schedule_account_sync"),
            patch(f"{COMPLETION}.capture_event") as capture,
        ):
            completion = await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert completion.first_contact_delivered is True
        notify.assert_not_called()
        capture.assert_not_called()


class TestRefusedLinkSpendsNothing:
    async def test_conflict_is_409_with_no_side_effects(self) -> None:
        with (
            patch(
                "app.services.platform_link_service.PlatformLinkService.link_account",
                new=AsyncMock(side_effect=PlatformAccountTakenError("already linked")),
            ),
            patch(f"{COMPLETION}.publish_outbound_message", new=AsyncMock()) as publish,
            patch(f"{COMPLETION}.notify_account_linked", new=AsyncMock()) as notify,
            patch(f"{COMPLETION}.capture_event") as capture,
        ):
            with pytest.raises(AppError) as exc_info:
                await complete_platform_link(USER_ID, "telegram", PLATFORM_USER_ID)

        assert exc_info.value.status_code == 409
        publish.assert_not_awaited()
        notify.assert_not_awaited()
        capture.assert_not_called()


class TestOutboundPublishResolvesAndEnvelopes:
    async def test_unlinked_account_skips_without_touching_the_broker(self) -> None:
        with (
            patch(
                "app.services.outbound_delivery.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.outbound_delivery.get_rabbitmq_publisher",
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
                "app.services.outbound_delivery.PlatformLinkService.get_linked_platforms",
                new=AsyncMock(return_value={"telegram": {"platformUserId": PLATFORM_USER_ID}}),
            ),
            patch(
                "app.services.outbound_delivery.get_rabbitmq_publisher",
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
