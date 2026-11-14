"""PUT /bot/conversations/{id}/delivered: a bot's report moves its session's cursor, behind the bot key."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints import bot_conversations as endpoint
from app.constants.chat import ConversationSource
from app.models.bot_models import PartialReply
from app.models.conversation_send_models import BotDeliveryRecorded, BotDeliveryReport

pytestmark = pytest.mark.unit

REPORT = BotDeliveryReport(
    platform=ConversationSource.TELEGRAM,
    delivered_seq=7,
    partial_reply=PartialReply(reply_id="r8", bubbles=1),
)


@pytest.mark.parametrize("recorded", [True, False])
async def test_the_report_is_recorded_on_the_conversations_session_for_its_platform(
    recorded: bool,
) -> None:
    request = MagicMock()
    with (
        patch.object(endpoint, "require_bot_api_key", new=AsyncMock()) as key,
        patch.object(
            endpoint.bot_session_repository,
            "record_delivered",
            new=AsyncMock(return_value=recorded),
        ) as record,
    ):
        response = await endpoint.record_delivered(request, "conv-1", REPORT)

    key.assert_awaited_once_with(request)
    record.assert_awaited_once_with(
        "conv-1", platform="telegram", delivered_seq=7, partial_reply=REPORT.partial_reply
    )
    assert response == BotDeliveryRecorded(recorded=recorded)


async def test_a_report_without_the_bot_key_records_nothing() -> None:
    with (
        patch.object(
            endpoint, "require_bot_api_key", new=AsyncMock(side_effect=PermissionError("no key"))
        ),
        patch.object(
            endpoint.bot_session_repository, "record_delivered", new=AsyncMock()
        ) as record,
        pytest.raises(PermissionError),
    ):
        await endpoint.record_delivered(MagicMock(), "conv-1", REPORT)

    record.assert_not_awaited()
