"""A proactive notification sent to a chat platform must be in the agent's memory of that chat.

A notification GAIA pushes to Telegram on its own initiative (the agent's
send_notification, a stale-todo nudge) went out through the outbound queue only:
it never reached the DM conversation's Mongo history or its LangGraph
checkpoint. So when the user replied "yes, chase them", the next bot turn ran on
a thread with no trace of what GAIA had just said, and answered blind. The
workflow-result path already wrote both; the notification adapter did not.

This drives the real Telegram notification adapter and then a real comms turn
on the same thread, and asserts the model was shown the proactive message.
Only the outward edges are doubled: the user lookup, the bot session lookup,
the Mongo append, and the RabbitMQ publisher.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.core.graph_manager import GraphManager
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.models.user_models import UserDocument
from app.services.bot_service import BotService
from app.services.platform_link_service import PlatformLinkService
from app.utils.notification.channels.telegram import TelegramChannelAdapter
from tests.e2e._harness.graph_run import comms_graph, run_graph
from tests.helpers import quiet_hours_excluding_now

pytestmark = pytest.mark.e2e

USER_ID = "507f1f77bcf86cd799439011"
TELEGRAM_ID = "tg-42"
NUDGE = "Acme's invoice is three days overdue. Want me to chase them?"


@pytest.mark.regression
async def test_a_proactive_notification_is_in_the_next_bot_turns_memory() -> None:
    thread_id = f"conv-{uuid4()}"
    user = UserDocument(
        id=USER_ID,
        platform_links={"telegram": {"id": TELEGRAM_ID}},
        timezone="UTC",
        quiet_hours=quiet_hours_excluding_now(),
    )
    publisher = MagicMock(publish_outbound=AsyncMock())
    request = NotificationRequest(
        user_id=USER_ID,
        source=NotificationSourceEnum.AI_AGENT,
        type=NotificationType.INFO,
        content=NotificationContent(title="Invoice overdue", body=NUDGE),
    )

    async with comms_graph(["On it, I'll chase Acme now."]) as graph:
        with (
            patch.object(GraphManager, "get_graph", new=AsyncMock(return_value=graph)),
            patch.object(user_repository, "get", new=AsyncMock(return_value=user)),
            patch.object(
                PlatformLinkService,
                "get_linked_platforms",
                new=AsyncMock(return_value={"telegram": {"platformUserId": TELEGRAM_ID}}),
            ),
            patch.object(
                BotService, "get_or_create_session", new=AsyncMock(return_value=thread_id)
            ),
            patch.object(
                conversation_repository, "append_messages", new=AsyncMock(return_value=["m-1"])
            ) as saved,
            patch(
                "app.services.outbound_delivery.get_rabbitmq_publisher",
                new=AsyncMock(return_value=publisher),
            ),
        ):
            adapter = TelegramChannelAdapter()
            status = await adapter.deliver(await adapter.transform(request), USER_ID)

        run = await run_graph(graph, "yes please, chase them", thread_id=thread_id)

    shown = [str(getattr(message, "content", "")) for message in run.prompts[0]]
    assert any(NUDGE in content for content in shown), shown
    assert status.status == NotificationStatus.DELIVERED
    publisher.publish_outbound.assert_awaited_once()
    assert saved.await_args.args[0] == thread_id
