"""send_notification: a named channel gets one notification per tool call, and the tool reports where it landed."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools.notification_tool import result_is_delivered_automatically, send_notification
from app.constants.tasks import Assignee
from app.models.agent_config import AgentConfigurableView
from app.models.notification.notification_models import (
    ChannelDeliveryStatus,
    NotificationContent,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    notification_id,
)
from app.models.task_models import TaskDocument
from shared.py.analytics import UserId
from shared.py.analytics.catalog.notifications import NotificationAgentSent
from tests.factories import make_user_id

MODULE = "app.agents.tools.notification_tool"


def _send() -> Callable[..., Awaitable[object]]:
    """Return the tool's coroutine, called with the injected config and call id as the tool node does."""
    assert isinstance(send_notification, StructuredTool) and send_notification.coroutine is not None
    return send_notification.coroutine


@dataclass
class Seams:
    notify: AsyncMock
    capture: MagicMock
    writer: MagicMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    writer = MagicMock()
    with (
        patch(f"{MODULE}.notification_service") as service,
        patch(f"{MODULE}.capture") as capture,
        patch(f"{MODULE}.current_stream_writer", return_value=writer),
    ):
        service.notify = AsyncMock()
        yield Seams(service.notify, capture, writer)


def _record(channels: list[ChannelDeliveryStatus]) -> SimpleNamespace:
    return SimpleNamespace(
        record=SimpleNamespace(id="n-1", status=NotificationStatus.DELIVERED, channels=channels)
    )


async def test_a_named_channel_is_notified_once_per_tool_call(seams: Seams) -> None:
    user_id = make_user_id()
    seams.notify.return_value = _record(
        [
            ChannelDeliveryStatus(channel_type="telegram", status=NotificationStatus.DELIVERED),
            ChannelDeliveryStatus(
                channel_type="inapp", status=NotificationStatus.DELIVERED, skipped=True
            ),
            ChannelDeliveryStatus(channel_type="slack", status=NotificationStatus.FAILED),
        ]
    )

    result = await _send()(
        config={"configurable": {"user_id": user_id}},
        tool_call_id="call-7",
        message="  Build failed on main  ",
        title=" Build failed ",
        channels=["telegram", "slack"],
        notification_type=NotificationType.ERROR,
    )

    (request,) = seams.notify.await_args.args
    assert request.id == notification_id(user_id, "agent_notification", "call-7")
    assert request.user_id == user_id
    assert request.source is NotificationSourceEnum.AI_AGENT
    assert request.type is NotificationType.ERROR
    assert [channel.channel_type for channel in request.channels] == ["telegram", "slack"]
    assert request.content == NotificationContent(title="Build failed", body="Build failed on main")
    seams.capture.assert_called_once_with(UserId(user_id), NotificationAgentSent(outcome="sent"))
    assert result == {
        "success": True,
        "notification_id": "n-1",
        "title": "Build failed",
        "message": "Build failed on main",
        "notification_type": "error",
        "status": NotificationStatus.DELIVERED.value,
        "delivered_channels": ["telegram"],
    }
    seams.writer.assert_called_once_with({"send_notification_data": result})


async def test_a_replayed_tool_call_reuses_its_notification_id(seams: Seams) -> None:
    user_id = make_user_id()
    seams.notify.return_value = _record([])
    config = {"configurable": {"user_id": user_id}}

    for call_id in ("call-1", "call-1", "call-2"):
        await _send()(
            config=config, tool_call_id=call_id, message="hi", title="Hey", channels=["telegram"]
        )

    ids = [call.args[0].id for call in seams.notify.await_args_list]
    assert ids[0] == ids[1] != ids[2]


@pytest.mark.parametrize(("notify", "delivered"), [(True, True), (False, False)])
async def test_a_gaia_task_run_counts_as_delivered_exactly_when_the_task_tells_the_user(
    notify: bool, delivered: bool
) -> None:
    user_id = make_user_id()
    task = TaskDocument(
        user_id=user_id, title="Watch the slots", assignee=Assignee.GAIA, notify=notify
    )
    configurable = AgentConfigurableView(execution_mode="background", active_task_id=task.id)
    with patch(f"{MODULE}.task_repository.get", AsyncMock(return_value=task)) as get:
        assert await result_is_delivered_automatically(configurable, user_id) is delivered
    get.assert_awaited_once_with(task.id, user_id=user_id)
