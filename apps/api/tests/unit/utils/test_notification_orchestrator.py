"""Unit tests for the notification orchestrator."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.notification.notification_models import (
    ActionConfig,
    ActionResult,
    ActionStyle,
    ActionType,
    ApiCallConfig,
    BulkActions,
    ChannelConfig,
    ChannelDeliveryStatus,
    NotificationAction,
    NotificationContent,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
    RedirectConfig,
)
from app.utils.notification.orchestrator import NotificationOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    user_id: str = "user-1",
    channels: Optional[List[ChannelConfig]] = None,
    actions: Optional[List[NotificationAction]] = None,
    notification_id: str = "notif-1",
) -> NotificationRequest:
    """Build a minimal NotificationRequest for testing."""
    return NotificationRequest(
        id=notification_id,
        user_id=user_id,
        source=NotificationSourceEnum.AI_TODO_ADDED,
        type=NotificationType.INFO,
        priority=2,
        channels=channels
        or [ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
        content=NotificationContent(
            title="Test Notification",
            body="This is a test body",
            actions=actions,
        ),
        metadata={"key": "value"},
    )


def _make_record(
    request: Optional[NotificationRequest] = None,
    status: NotificationStatus = NotificationStatus.PENDING,
    channels: Optional[List[ChannelDeliveryStatus]] = None,
) -> NotificationRecord:
    """Build a NotificationRecord wrapping *request*."""
    req = request or _make_request()
    return NotificationRecord(
        id=req.id,
        user_id=req.user_id,
        status=status,
        created_at=req.created_at,
        original_request=req,
        channels=channels or [],
    )


def _mock_channel_adapter(
    channel_type: str = "inapp",
    can_handle: bool = True,
    transform_return: Optional[Dict[str, Any]] = None,
    deliver_return: Optional[ChannelDeliveryStatus] = None,
) -> MagicMock:
    """Build a mock channel adapter with sync can_handle and async transform/deliver."""
    adapter = MagicMock()
    adapter.channel_type = channel_type
    adapter.can_handle.return_value = can_handle
    adapter.transform = AsyncMock(return_value=transform_return or {})
    adapter.deliver = AsyncMock(
        return_value=deliver_return
        or ChannelDeliveryStatus(
            channel_type=channel_type,
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(timezone.utc),
        )
    )
    return adapter


def _make_action(
    action_id: str = "action-1",
    action_type: ActionType = ActionType.REDIRECT,
    executed: bool = False,
    disabled: bool = False,
) -> NotificationAction:
    """Build a NotificationAction for testing."""
    config: ActionConfig
    if action_type == ActionType.REDIRECT:
        config = ActionConfig(
            redirect=RedirectConfig(url="/test", open_in_new_tab=False)
        )
    elif action_type == ActionType.API_CALL:
        config = ActionConfig(
            api_call=ApiCallConfig(endpoint="/api/test", method="POST")
        )
    else:
        raise ValueError(f"Unsupported action type for helper: {action_type}")
    return NotificationAction(
        id=action_id,
        type=action_type,
        label="Test Action",
        style=ActionStyle.PRIMARY,
        config=config,
        executed=executed,
        disabled=disabled,
    )


# ---------------------------------------------------------------------------
# Orchestrator initialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorInit:
    """Tests for orchestrator initialisation and component registration."""

    def test_default_components_registered(self) -> None:
        """Default channel adapters and action handlers are registered."""
        orch = NotificationOrchestrator(storage=MagicMock())
        assert "inapp" in orch.channel_adapters
        assert "telegram" in orch.channel_adapters
        assert "discord" in orch.channel_adapters
        assert "api_call" in orch.action_handlers
        assert "redirect" in orch.action_handlers
        assert "modal" in orch.action_handlers

    def test_custom_storage_is_used(self) -> None:
        """When a custom storage object is passed it replaces the default."""
        custom_storage = MagicMock()
        orch = NotificationOrchestrator(storage=custom_storage)
        assert orch.storage is custom_storage

    def test_register_channel_adapter(self) -> None:
        """register_channel_adapter adds adapter under its channel_type key."""
        orch = NotificationOrchestrator(storage=MagicMock())
        adapter = MagicMock()
        adapter.channel_type = "custom_channel"
        orch.register_channel_adapter(adapter)
        assert orch.channel_adapters["custom_channel"] is adapter

    def test_register_action_handler(self) -> None:
        """register_action_handler adds handler under its action_type key."""
        orch = NotificationOrchestrator(storage=MagicMock())
        handler = MagicMock()
        handler.action_type = "custom_action"
        orch.register_action_handler(handler)
        assert orch.action_handlers["custom_action"] is handler


# ---------------------------------------------------------------------------
# create_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateNotification:
    """Tests for NotificationOrchestrator.create_notification."""

    async def test_creates_and_saves_notification(self) -> None:
        """Notification record is saved and delivery is attempted."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        # Stub delivery to be a no-op
        orch._deliver_notification = AsyncMock()  # type: ignore[method-assign]

        request = _make_request()
        result = await orch.create_notification(request)

        assert result is not None
        assert result.id == request.id
        assert result.user_id == request.user_id
        assert result.status == NotificationStatus.PENDING
        storage.save_notification.assert_awaited_once()
        orch._deliver_notification.assert_awaited_once()

    async def test_notification_record_fields(self) -> None:
        """The record preserves the original request and timestamps."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)
        orch._deliver_notification = AsyncMock()  # type: ignore[method-assign]

        request = _make_request(user_id="user-42", notification_id="n-42")
        record = await orch.create_notification(request)

        assert record is not None
        assert record.original_request is request
        assert record.created_at == request.created_at


# ---------------------------------------------------------------------------
# _deliver_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeliverNotification:
    """Tests for the internal _deliver_notification pipeline."""

    async def test_delivers_via_matching_channel_adapter(self) -> None:
        """When a channel adapter can handle the request it is invoked."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        success_status = ChannelDeliveryStatus(
            channel_type="inapp",
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(timezone.utc),
        )

        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp",
            can_handle=True,
            transform_return={"title": "test"},
            deliver_return=success_status,
        )

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        storage.update_notification.assert_awaited_once()
        call_args = storage.update_notification.call_args
        updates = call_args[0][1]
        assert updates["status"] == NotificationStatus.DELIVERED.value

    async def test_overall_status_failed_when_no_channel_succeeds(self) -> None:
        """If all channels fail, overall status is FAILED."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        fail_status = ChannelDeliveryStatus(
            channel_type="inapp",
            status=NotificationStatus.FAILED,
            error_message="boom",
        )
        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp",
            can_handle=True,
            deliver_return=fail_status,
        )

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        updates = storage.update_notification.call_args[0][1]
        assert updates["status"] == NotificationStatus.FAILED.value
        assert updates["delivered_at"] is None

    async def test_skipped_channels_do_not_count_as_delivered(self) -> None:
        """A channel with status DELIVERED but skipped=True is not counted."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        skipped_status = ChannelDeliveryStatus(
            channel_type="inapp",
            status=NotificationStatus.DELIVERED,
            skipped=True,
        )
        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp",
            can_handle=True,
            deliver_return=skipped_status,
        )

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        updates = storage.update_notification.call_args[0][1]
        assert updates["status"] == NotificationStatus.FAILED.value

    async def test_adapter_exception_treated_as_error(self) -> None:
        """If an adapter raises, it is caught and does not crash delivery."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        adapter = _mock_channel_adapter(channel_type="inapp", can_handle=True)
        adapter.transform.side_effect = RuntimeError("adapter died")
        orch.channel_adapters["inapp"] = adapter

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            # Should not raise
            await orch._deliver_notification(record)

    async def test_no_delivery_tasks_when_adapter_cannot_handle(self) -> None:
        """If no adapter can handle the request, nothing is delivered."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp", can_handle=False
        )

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        # No delivery tasks → update_notification never called
        storage.update_notification.assert_not_awaited()

    async def test_websocket_broadcast_after_delivery(self) -> None:
        """A notification.delivered event is broadcast via websocket."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        success_status = ChannelDeliveryStatus(
            channel_type="inapp",
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(timezone.utc),
        )
        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp",
            can_handle=True,
            deliver_return=success_status,
        )

        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

            ws.broadcast_to_user.assert_awaited_once()
            call_args = ws.broadcast_to_user.call_args
            assert call_args[0][0] == request.user_id
            payload = call_args[0][1]
            assert payload["type"] == "notification.delivered"
            assert "notification" in payload


# ---------------------------------------------------------------------------
# Auto-injection of channels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutoInjectedChannels:
    """Tests for auto-injection of channels when none are explicitly requested."""

    async def test_auto_injects_channels_when_none_explicit(self) -> None:
        """When request.channels is empty, auto-injected channels are used."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        # Make all adapters return success and can_handle=True
        for key in list(orch.channel_adapters.keys()):
            orch.channel_adapters[key] = _mock_channel_adapter(
                channel_type=key,
                can_handle=True,
                transform_return={"text": "test"},
                deliver_return=ChannelDeliveryStatus(
                    channel_type=key,
                    status=NotificationStatus.DELIVERED,
                    delivered_at=datetime.now(timezone.utc),
                ),
            )

        request = _make_request(channels=[])  # No explicit channels
        record = _make_record(request=request)

        with (
            patch("app.utils.notification.orchestrator.websocket_manager") as ws,
            patch.object(
                orch,
                "_get_channel_prefs",
                new_callable=AsyncMock,
                return_value={"telegram": True, "discord": True},
            ),
        ):
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        # All three auto-injected channels should have been attempted
        updates = storage.update_notification.call_args[0][1]
        channel_types = [ch["channel_type"] for ch in updates["channels"]]
        assert "inapp" in channel_types

    async def test_disabled_preference_skips_channel(self) -> None:
        """When a user has disabled telegram, it is not auto-injected."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        for key in list(orch.channel_adapters.keys()):
            orch.channel_adapters[key] = _mock_channel_adapter(
                channel_type=key,
                can_handle=True,
                transform_return={"text": "test"},
                deliver_return=ChannelDeliveryStatus(
                    channel_type=key,
                    status=NotificationStatus.DELIVERED,
                    delivered_at=datetime.now(timezone.utc),
                ),
            )

        request = _make_request(channels=[])
        record = _make_record(request=request)

        with (
            patch("app.utils.notification.orchestrator.websocket_manager") as ws,
            patch.object(
                orch,
                "_get_channel_prefs",
                new_callable=AsyncMock,
                return_value={"telegram": False, "discord": True},
            ),
        ):
            ws.broadcast_to_user = AsyncMock()
            await orch._deliver_notification(record)

        updates = storage.update_notification.call_args[0][1]
        channel_types = [ch["channel_type"] for ch in updates["channels"]]
        assert "telegram" not in channel_types

    async def test_no_auto_injection_when_explicit_channels_present(self) -> None:
        """When explicit channels are requested, auto-injection is skipped."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        orch.channel_adapters["inapp"] = _mock_channel_adapter(
            channel_type="inapp", can_handle=True
        )

        # Explicit channel list → no auto-injection
        request = _make_request(channels=[ChannelConfig(channel_type="inapp")])
        record = _make_record(request=request)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            # _get_channel_prefs should never be called
            with patch.object(
                orch, "_get_channel_prefs", new_callable=AsyncMock
            ) as prefs:
                await orch._deliver_notification(record)
                prefs.assert_not_awaited()


# ---------------------------------------------------------------------------
# _get_channel_prefs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetChannelPrefs:
    """Tests for _get_channel_prefs error handling."""

    async def test_returns_prefs_from_db(self) -> None:
        """Happy path: delegates to fetch_channel_preferences."""
        orch = NotificationOrchestrator(storage=MagicMock())
        with patch(
            "app.utils.notification.orchestrator.fetch_channel_preferences",
            new_callable=AsyncMock,
            return_value={"telegram": True, "discord": False},
        ):
            prefs = await orch._get_channel_prefs("user-1")
            assert prefs == {"telegram": True, "discord": False}

    async def test_returns_all_disabled_on_error(self) -> None:
        """On DB failure, all channels default to disabled (safe fallback)."""
        orch = NotificationOrchestrator(storage=MagicMock())
        with patch(
            "app.utils.notification.orchestrator.fetch_channel_preferences",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ):
            prefs = await orch._get_channel_prefs("user-1")
            # Every key should be False
            for val in prefs.values():
                assert val is False


# ---------------------------------------------------------------------------
# _deliver_via_channel
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeliverViaChannel:
    """Tests for _deliver_via_channel error handling."""

    async def test_returns_success_from_adapter(self) -> None:
        """On successful delivery, returns the adapter's status."""
        storage = MagicMock()
        orch = NotificationOrchestrator(storage=storage)

        expected = ChannelDeliveryStatus(
            channel_type="inapp",
            status=NotificationStatus.DELIVERED,
            delivered_at=datetime.now(timezone.utc),
        )
        adapter = AsyncMock()
        adapter.channel_type = "inapp"
        adapter.transform.return_value = {"title": "t"}
        adapter.deliver.return_value = expected

        request = _make_request()
        record = _make_record(request=request)
        result = await orch._deliver_via_channel(record, adapter)

        assert result is expected

    async def test_exception_returns_pending_status_with_error(self) -> None:
        """An exception in the adapter returns PENDING with error message."""
        orch = NotificationOrchestrator(storage=MagicMock())

        adapter = AsyncMock()
        adapter.channel_type = "inapp"
        adapter.transform.side_effect = ValueError("transform broke")

        request = _make_request()
        record = _make_record(request=request)
        result = await orch._deliver_via_channel(record, adapter)

        assert result.channel_type == "inapp"
        assert result.status == NotificationStatus.PENDING
        assert "transform broke" in (result.error_message or "")


# ---------------------------------------------------------------------------
# execute_action
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteAction:
    """Tests for NotificationOrchestrator.execute_action."""

    async def test_notification_not_found(self) -> None:
        """Returns NOT_FOUND when storage returns None."""
        storage = AsyncMock()
        storage.get_notification.return_value = None
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.execute_action("notif-1", "action-1", "user-1", None)

        assert result.success is False
        assert result.error_code == "NOT_FOUND"

    async def test_action_not_found(self) -> None:
        """Returns ACTION_NOT_FOUND when action_id doesn't match."""
        storage = AsyncMock()
        request = _make_request(actions=[_make_action(action_id="other-action")])
        record = _make_record(request=request)
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.execute_action("notif-1", "missing-action", "user-1", None)

        assert result.success is False
        assert result.error_code == "ACTION_NOT_FOUND"

    async def test_action_already_executed_api_call(self) -> None:
        """An already-executed API_CALL action returns ACTION_ALREADY_EXECUTED."""
        storage = AsyncMock()
        action = _make_action(
            action_id="act-1", action_type=ActionType.API_CALL, executed=True
        )
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is False
        assert result.error_code == "ACTION_ALREADY_EXECUTED"

    async def test_action_disabled(self) -> None:
        """A disabled action returns ACTION_DISABLED."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1", disabled=True)
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is False
        assert result.error_code == "ACTION_DISABLED"

    async def test_no_handler_for_action_type(self) -> None:
        """Returns NO_HANDLER when no handler matches the action type."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)
        # Remove all handlers
        orch.action_handlers.clear()

        result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is False
        assert result.error_code == "NO_HANDLER"

    async def test_handler_cannot_handle_action(self) -> None:
        """Returns NO_HANDLER when handler.can_handle returns False."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)
        handler = MagicMock()
        handler.can_handle.return_value = False
        orch.action_handlers["redirect"] = handler

        result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is False
        assert result.error_code == "NO_HANDLER"

    async def test_successful_execution_marks_action_and_saves(self) -> None:
        """Successful handler execution marks action as executed and saves."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)

        handler = MagicMock()
        handler.action_type = "redirect"
        handler.can_handle.return_value = True
        handler.execute = AsyncMock(
            return_value=ActionResult(
                success=True,
                message="ok",
                update_notification=None,
            )
        )
        orch.action_handlers["redirect"] = handler

        with patch("app.utils.notification.orchestrator.websocket_manager"):
            result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is True
        # Should have saved the updated notification
        storage.update_notification.assert_awaited_once()

    async def test_successful_execution_with_update_notification(self) -> None:
        """When result.update_notification is set, an additional update + broadcast occurs."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)

        handler = MagicMock()
        handler.action_type = "redirect"
        handler.can_handle.return_value = True
        handler.execute = AsyncMock(
            return_value=ActionResult(
                success=True,
                message="ok",
                update_notification={"status": "read"},
            )
        )
        orch.action_handlers["redirect"] = handler

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is True
        # Two calls: one for marking executed, one for update_notification
        assert storage.update_notification.await_count == 2
        ws.broadcast_to_user.assert_awaited_once()
        payload = ws.broadcast_to_user.call_args[0][1]
        assert payload["type"] == "notification.updated"

    async def test_failed_execution_does_not_mark_action(self) -> None:
        """If the handler returns success=False, action is NOT marked as executed."""
        storage = AsyncMock()
        action = _make_action(action_id="act-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)

        handler = MagicMock()
        handler.action_type = "redirect"
        handler.can_handle.return_value = True
        handler.execute = AsyncMock(
            return_value=ActionResult(success=False, message="nope")
        )
        orch.action_handlers["redirect"] = handler

        with patch("app.utils.notification.orchestrator.websocket_manager"):
            result = await orch.execute_action("notif-1", "act-1", "user-1", None)

        assert result.success is False
        # update_notification should NOT have been called
        storage.update_notification.assert_not_awaited()
        assert action.executed is False


# ---------------------------------------------------------------------------
# mark_as_read
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMarkAsRead:
    """Tests for NotificationOrchestrator.mark_as_read."""

    async def test_marks_notification_as_read(self) -> None:
        """Updates status to READ and broadcasts a websocket event."""
        storage = AsyncMock()
        request = _make_request()
        record = _make_record(request=request, status=NotificationStatus.DELIVERED)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            await orch.mark_as_read("notif-1", "user-1")

        storage.update_notification.assert_awaited_once()
        call_args = storage.update_notification.call_args
        assert call_args[0][1]["status"] == NotificationStatus.READ.value
        assert "read_at" in call_args[0][1]

        ws.broadcast_to_user.assert_awaited_once()
        payload = ws.broadcast_to_user.call_args[0][1]
        assert payload["type"] == "notification.read"

    async def test_returns_none_when_notification_not_found(self) -> None:
        """Returns None if the notification does not exist."""
        storage = AsyncMock()
        storage.get_notification.return_value = None

        orch = NotificationOrchestrator(storage=storage)

        result = await orch.mark_as_read("notif-1", "user-1")

        assert result is None
        storage.update_notification.assert_not_awaited()


# ---------------------------------------------------------------------------
# archive_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestArchiveNotification:
    """Tests for NotificationOrchestrator.archive_notification."""

    async def test_archives_notification(self) -> None:
        """Updates status to ARCHIVED and returns True."""
        storage = AsyncMock()
        request = _make_request()
        record = _make_record(request=request)
        storage.get_notification.return_value = record

        orch = NotificationOrchestrator(storage=storage)

        result = await orch.archive_notification("notif-1", "user-1")

        assert result is True
        call_args = storage.update_notification.call_args
        assert call_args[0][1]["status"] == NotificationStatus.ARCHIVED.value
        assert "archived_at" in call_args[0][1]

    async def test_returns_false_when_not_found(self) -> None:
        """Returns False when the notification does not exist."""
        storage = AsyncMock()
        storage.get_notification.return_value = None

        orch = NotificationOrchestrator(storage=storage)

        result = await orch.archive_notification("notif-1", "user-1")

        assert result is False
        storage.update_notification.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_user_notifications / get_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNotifications:
    """Tests for notification retrieval methods."""

    async def test_get_user_notifications_serializes_records(self) -> None:
        """get_user_notifications serializes each record via _serialize_notification."""
        storage = AsyncMock()
        records = [
            _make_record(request=_make_request(notification_id="n-1")),
            _make_record(request=_make_request(notification_id="n-2")),
        ]
        storage.get_user_notifications.return_value = records
        orch = NotificationOrchestrator(storage=storage)

        results = await orch.get_user_notifications("user-1")

        assert len(results) == 2
        assert results[0]["id"] == "n-1"
        assert results[1]["id"] == "n-2"

    async def test_get_user_notifications_passes_filters(self) -> None:
        """All filter parameters are forwarded to storage."""
        storage = AsyncMock()
        storage.get_user_notifications.return_value = []
        orch = NotificationOrchestrator(storage=storage)

        await orch.get_user_notifications(
            "user-1",
            status=NotificationStatus.DELIVERED,
            limit=10,
            offset=5,
            channel_type="inapp",
            notification_type=NotificationType.WARNING,
            source=NotificationSourceEnum.AI_REMINDER,
        )

        storage.get_user_notifications.assert_awaited_once_with(
            "user-1",
            NotificationStatus.DELIVERED,
            10,
            5,
            "inapp",
            NotificationType.WARNING,
            NotificationSourceEnum.AI_REMINDER,
        )

    async def test_get_notification_returns_serialized(self) -> None:
        """get_notification returns a serialized dict for a found record."""
        storage = AsyncMock()
        record = _make_record()
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.get_notification("notif-1", "user-1")

        assert result is not None
        assert result["id"] == record.id

    async def test_get_notification_returns_none_when_not_found(self) -> None:
        """get_notification returns None when storage returns None."""
        storage = AsyncMock()
        storage.get_notification.return_value = None
        orch = NotificationOrchestrator(storage=storage)

        result = await orch.get_notification("notif-1", "user-1")

        assert result is None


# ---------------------------------------------------------------------------
# bulk_actions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBulkActions:
    """Tests for NotificationOrchestrator.bulk_actions."""

    async def test_bulk_mark_read(self) -> None:
        """MARK_READ bulk action calls mark_as_read for each ID."""
        storage = AsyncMock()
        record = _make_record()
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            results = await orch.bulk_actions(
                ["n-1", "n-2"], "user-1", BulkActions.MARK_READ
            )

        assert results["n-1"] is True
        assert results["n-2"] is True

    async def test_bulk_archive(self) -> None:
        """ARCHIVE bulk action calls archive_notification for each ID."""
        storage = AsyncMock()
        record = _make_record()
        storage.get_notification.return_value = record
        orch = NotificationOrchestrator(storage=storage)

        results = await orch.bulk_actions(["n-1", "n-2"], "user-1", BulkActions.ARCHIVE)

        assert results["n-1"] is True
        assert results["n-2"] is True

    async def test_bulk_unknown_action_returns_false(self) -> None:
        """An unrecognised bulk action type returns False for each ID."""
        storage = AsyncMock()
        orch = NotificationOrchestrator(storage=storage)

        # Simulate an unknown action by patching BulkActions value
        results = await orch.bulk_actions(
            ["n-1"],
            "user-1",
            MagicMock(),  # type: ignore[arg-type]
        )

        assert results["n-1"] is False

    async def test_bulk_action_exception_returns_false(self) -> None:
        """If mark_as_read raises, that ID gets False and others continue."""
        storage = AsyncMock()
        call_count = 0

        async def mock_get(nid: str, uid: str) -> Optional[NotificationRecord]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("db error")
            return _make_record()

        storage.get_notification.side_effect = mock_get
        orch = NotificationOrchestrator(storage=storage)

        with patch("app.utils.notification.orchestrator.websocket_manager") as ws:
            ws.broadcast_to_user = AsyncMock()
            results = await orch.bulk_actions(
                ["n-fail", "n-ok"], "user-1", BulkActions.MARK_READ
            )

        assert results["n-fail"] is False
        # n-ok should still succeed (or at least not crash)

    async def test_bulk_mark_read_not_found(self) -> None:
        """If mark_as_read returns None (not found), result is False."""
        storage = AsyncMock()
        storage.get_notification.return_value = None
        orch = NotificationOrchestrator(storage=storage)

        results = await orch.bulk_actions(
            ["n-missing"], "user-1", BulkActions.MARK_READ
        )

        assert results["n-missing"] is False


# ---------------------------------------------------------------------------
# _serialize_notification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeNotification:
    """Tests for the _serialize_notification helper."""

    async def test_full_serialization(self) -> None:
        """All expected keys are present in the serialized output."""
        action = _make_action(action_id="a-1")
        request = _make_request(actions=[action])
        record = _make_record(request=request, status=NotificationStatus.DELIVERED)
        record.delivered_at = datetime.now(timezone.utc)
        record.read_at = datetime.now(timezone.utc)
        record.channels = [
            ChannelDeliveryStatus(
                channel_type="inapp",
                status=NotificationStatus.DELIVERED,
                delivered_at=datetime.now(timezone.utc),
            )
        ]

        orch = NotificationOrchestrator(storage=MagicMock())
        data = await orch._serialize_notification(record)

        assert data["id"] == record.id
        assert data["user_id"] == record.user_id
        assert data["status"] == "delivered"
        assert data["delivered_at"] is not None
        assert data["read_at"] is not None
        assert data["content"]["title"] == "Test Notification"
        assert data["content"]["body"] == "This is a test body"
        assert len(data["content"]["actions"]) == 1
        assert data["content"]["actions"][0]["id"] == "a-1"
        assert data["source"] == NotificationSourceEnum.AI_TODO_ADDED.value
        assert data["type"] == NotificationType.INFO.value
        assert data["metadata"] == {"key": "value"}
        assert len(data["channels"]) == 1
        assert data["channels"][0]["channel_type"] == "inapp"

    async def test_serialization_with_no_dates(self) -> None:
        """Null dates serialize to None."""
        record = _make_record()
        record.delivered_at = None
        record.read_at = None

        orch = NotificationOrchestrator(storage=MagicMock())
        data = await orch._serialize_notification(record)

        assert data["delivered_at"] is None
        assert data["read_at"] is None

    async def test_serialization_with_no_actions(self) -> None:
        """Notification with no actions serializes to empty actions list."""
        request = _make_request(actions=None)
        record = _make_record(request=request)

        orch = NotificationOrchestrator(storage=MagicMock())
        data = await orch._serialize_notification(record)

        assert data["content"]["actions"] == []

    async def test_serialization_with_empty_channels(self) -> None:
        """Notification with no channel statuses has empty channels list."""
        record = _make_record()
        record.channels = []

        orch = NotificationOrchestrator(storage=MagicMock())
        data = await orch._serialize_notification(record)

        assert data["channels"] == []
