"""Unit tests for publish_outbound_message — the outbound RabbitMQ publisher
that replaces direct platform HTTP sends."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.services import outbound_delivery as od


@pytest.mark.unit
class TestPublishOutboundMessage:
    async def test_unlinked_account_returns_false(self) -> None:
        with patch.object(
            od.PlatformLinkService,
            "get_linked_platforms",
            new_callable=AsyncMock,
            return_value={},
        ):
            ok = await od.publish_outbound_message(ConversationSource.WHATSAPP, "user-1", ["hi"])
        assert ok is False

    async def test_no_non_blank_parts_returns_false(self) -> None:
        with patch.object(
            od.PlatformLinkService, "get_linked_platforms", new_callable=AsyncMock
        ) as linked:
            ok = await od.publish_outbound_message(
                ConversationSource.WHATSAPP, "user-1", ["  ", ""]
            )
        assert ok is False
        linked.assert_not_awaited()  # short-circuits before the link lookup

    async def test_broker_unavailable_returns_false(self) -> None:
        with (
            patch.object(
                od.PlatformLinkService,
                "get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"whatsapp": {"platformUserId": "15551234567"}},
            ),
            patch.object(
                od,
                "get_rabbitmq_publisher",
                new_callable=AsyncMock,
                side_effect=RuntimeError("down"),
            ),
        ):
            ok = await od.publish_outbound_message(ConversationSource.WHATSAPP, "user-1", ["hi"])
        assert ok is False

    async def test_publishes_one_envelope_per_non_blank_part(self) -> None:
        publisher = AsyncMock()
        with (
            patch.object(
                od.PlatformLinkService,
                "get_linked_platforms",
                new_callable=AsyncMock,
                return_value={"whatsapp": {"platformUserId": "15551234567"}},
            ),
            patch.object(
                od, "get_rabbitmq_publisher", new_callable=AsyncMock, return_value=publisher
            ),
        ):
            ok = await od.publish_outbound_message(
                ConversationSource.WHATSAPP, "user-1", ["hi", "   ", "there"]
            )
        assert ok is True
        # The blank middle part is dropped → two envelopes on the whatsapp queue.
        assert publisher.publish_outbound.await_count == 2
        queue, body = publisher.publish_outbound.await_args_list[0].args
        assert queue == "outbound.whatsapp"
        assert b"15551234567" in body  # envelope carries the resolved destination


def _linked(platform: str, platform_user_id: object) -> dict[str, dict[str, object]]:
    return {platform: {"platformUserId": platform_user_id}}


@pytest.mark.unit
class TestPublishOutboundMessageBrutalEdges:
    async def test_int_destination_is_coerced_to_string_in_envelope(self) -> None:
        # Telegram stores chat_id as an int. The envelope field is a str, so the
        # service must coerce — without ``str()`` Pydantic raises and we'd drop
        # every Telegram message.
        publisher = AsyncMock()
        with (
            patch.object(
                od.PlatformLinkService,
                "get_linked_platforms",
                new_callable=AsyncMock,
                return_value=_linked("telegram", 123456789),
            ),
            patch.object(
                od, "get_rabbitmq_publisher", new_callable=AsyncMock, return_value=publisher
            ),
        ):
            ok = await od.publish_outbound_message(ConversationSource.TELEGRAM, "u1", ["hi"])
        assert ok is True
        _queue, body = publisher.publish_outbound.await_args.args
        envelope = json.loads(body)
        assert envelope["destination_id"] == "123456789"

    async def test_unicode_text_round_trips_through_the_envelope(self) -> None:
        publisher = AsyncMock()
        text = 'café — "quote" 🎉\nsecond line'
        with (
            patch.object(
                od.PlatformLinkService,
                "get_linked_platforms",
                new_callable=AsyncMock,
                return_value=_linked("whatsapp", "15551234567"),
            ),
            patch.object(
                od, "get_rabbitmq_publisher", new_callable=AsyncMock, return_value=publisher
            ),
        ):
            ok = await od.publish_outbound_message(ConversationSource.WHATSAPP, "u1", [text])
        assert ok is True
        _queue, body = publisher.publish_outbound.await_args.args
        assert json.loads(body.decode("utf-8"))["text"] == text

    async def test_partial_publish_failure_returns_false_after_sending_earlier_parts(
        self,
    ) -> None:
        # At-least-once reality: the first part is already on the wire when the
        # second fails. The function reports False but does NOT un-send part one.
        publisher = AsyncMock()
        publisher.publish_outbound = AsyncMock(side_effect=[None, RuntimeError("boom")])
        with (
            patch.object(
                od.PlatformLinkService,
                "get_linked_platforms",
                new_callable=AsyncMock,
                return_value=_linked("whatsapp", "15551234567"),
            ),
            patch.object(
                od, "get_rabbitmq_publisher", new_callable=AsyncMock, return_value=publisher
            ),
        ):
            ok = await od.publish_outbound_message(ConversationSource.WHATSAPP, "u1", ["a", "b"])
        assert ok is False
        assert publisher.publish_outbound.await_count == 2
