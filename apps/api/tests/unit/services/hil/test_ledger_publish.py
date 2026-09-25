"""Ledger card publish: register emits a PENDING card, dedup emits nothing."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.hil_models import LedgerState

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_request

MODULE = "app.services.hil.gate"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


def _request(**overrides: Any):
    return make_request(
        name="GMAIL_SEND_EMAIL",
        args={"to": "b@x"},
        configurable={
            "stream_id": STREAM_ID,
            "user_id": USER_ID,
            "conversation_id": CONVERSATION_ID,
            "user_messages": ["send it"],
            **overrides,
        },
    )


def _ledger(
    live: Any = None, denied: Any = None, registered_id: str = "ap_abc1234567"
) -> MagicMock:
    ledger = MagicMock()
    ledger.find_live = AsyncMock(return_value=live)
    ledger.find_latest_denied = AsyncMock(return_value=denied)
    ledger.register = AsyncMock(return_value=registered_id)
    return ledger


@pytest.mark.unit
class TestLedgerPublish:
    async def test_register_publishes_pending_card_once(self) -> None:
        from app.services.hil import gate

        ledger = _ledger()
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=ledger),
            patch(f"{MODULE}._integration_name_for", new=AsyncMock(return_value="gmail")),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
        ):
            await gate.decide_tool_call(_request())

        ledger.register.assert_awaited_once()
        pub.assert_awaited_once()
        assert pub.await_args.args[0].approval_id == "ap_abc1234567"
        assert pub.await_args.args[0].conversation_id == CONVERSATION_ID

    async def test_live_duplicate_publishes_nothing(self) -> None:
        from app.services.hil import gate

        live = MagicMock(approval_id="ap_live", summary="Send it")
        live.state = LedgerState.PENDING
        with (
            patch(f"{MODULE}.is_hil_ledger_enabled", new=AsyncMock(return_value=True)),
            patch(f"{MODULE}.resolve_policy", new=AsyncMock(return_value="ask")),
            patch(f"{MODULE}.approval_ledger_repository", new=_ledger(live=live)),
            patch(f"{MODULE}.publish_ledger_request", new=AsyncMock()) as pub,
        ):
            result = await gate.decide_tool_call(_request())

        pub.assert_not_awaited()
        assert result is not None
        assert "ap_live" in str(result.content)


@pytest.mark.unit
class TestLedgerPublishHold:
    """Live runs hold PENDING cards until the run ends; a mid-run revoke is never shown.

    Background runs publish immediately — nobody is watching.
    """

    def _session(self, stream_id: str):
        from app.agents.core.background.session import RunKind, create_session

        return create_session(stream_id, RunKind.LIVE)

    def _teardown(self, stream_id: str) -> None:
        from app.agents.core.background.session import teardown_session

        teardown_session(stream_id)

    async def test_live_run_holds_sse_and_notify_but_records_session(self) -> None:
        from app.services.hil.bridge import GatedApproval, publish_ledger_request
        from app.services.hil.utils import GatedCall

        stream_id = "stream-hold-test"
        self._session(stream_id)
        try:
            with (
                patch(
                    "app.services.hil.bridge.stream_manager.publish_chunk",
                    new=AsyncMock(),
                ) as chunk,
                patch("app.services.hil.bridge._schedule_pending_notification") as notify,
            ):
                await publish_ledger_request(
                    GatedApproval(
                        approval_id="ap_hold",
                        stream_id=stream_id,
                        user_id="u1",
                        conversation_id="conv-1",
                        tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}),
                        summary="Send it",
                        integration_name="gmail",
                    ),
                )
            chunk.assert_not_awaited()
            notify.assert_not_called()
            from app.agents.core.background.session import get_session

            frames = get_session(stream_id).tool_events
            assert len(frames) == 1
            assert frames[0]["tool_data"]["data"]["approval_id"] == "ap_hold"
            assert frames[0]["tool_data"]["data"]["status"] == "pending"
        finally:
            self._teardown(stream_id)

    async def test_live_run_without_session_publishes_immediately(self) -> None:
        """No session means no drain will ever persist the frame — holding would hide the card until a drain that never comes."""
        from app.services.hil.bridge import GatedApproval, publish_ledger_request
        from app.services.hil.utils import GatedCall

        with (
            patch(
                "app.services.hil.bridge.stream_manager.publish_chunk",
                new=AsyncMock(),
            ) as chunk,
            patch("app.services.hil.bridge._schedule_pending_notification") as notify,
        ):
            await publish_ledger_request(
                GatedApproval(
                    approval_id="ap_nosession",
                    stream_id="stream-without-session",
                    user_id="u1",
                    conversation_id="conv-1",
                    tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}),
                    summary="Send it",
                    integration_name="gmail",
                ),
            )
        chunk.assert_awaited_once()
        notify.assert_called_once()

    async def test_queued_session_publishes_immediately(self) -> None:
        """Detached queued runs have a session but no watcher — holding would park the card on an unwatched stream."""
        from app.agents.core.background.session import RunKind, create_session
        from app.services.hil.bridge import GatedApproval, publish_ledger_request
        from app.services.hil.utils import GatedCall

        stream_id = "stream-queued-test"
        create_session(stream_id, RunKind.QUEUED)
        try:
            with (
                patch(
                    "app.services.hil.bridge.stream_manager.publish_chunk",
                    new=AsyncMock(),
                ) as chunk,
                patch("app.services.hil.bridge._schedule_pending_notification") as notify,
            ):
                await publish_ledger_request(
                    GatedApproval(
                        approval_id="ap_queued",
                        stream_id=stream_id,
                        user_id="u1",
                        conversation_id="conv-1",
                        tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}),
                        summary="Send it",
                        integration_name="gmail",
                    ),
                )
            chunk.assert_awaited_once()
            notify.assert_called_once()
        finally:
            self._teardown(stream_id)

    async def test_background_run_publishes_immediately(self) -> None:
        from app.services.hil.bridge import GatedApproval, publish_ledger_request
        from app.services.hil.utils import GatedCall

        stream_id = "stream-bg-test"
        self._session(stream_id)
        try:
            with (
                patch(
                    "app.services.hil.bridge.stream_manager.publish_chunk",
                    new=AsyncMock(),
                ) as chunk,
                patch("app.services.hil.bridge._schedule_pending_notification") as notify,
            ):
                await publish_ledger_request(
                    GatedApproval(
                        approval_id="ap_bg",
                        stream_id=stream_id,
                        user_id="u1",
                        conversation_id="conv-1",
                        tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}),
                        summary="Send it",
                        integration_name="gmail",
                    ),
                    live=False,
                )
            chunk.assert_awaited_once()
            notify.assert_called_once()
        finally:
            self._teardown(stream_id)

    async def test_revoke_drops_held_frame_instead_of_tombstoning(self) -> None:
        """A revoke before the run ends removes the unshown frame: the drain persists nothing and the user never knows the card existed."""
        from app.services.hil import ledger_decide
        from app.services.hil.bridge import GatedApproval, publish_ledger_request
        from app.services.hil.utils import GatedCall

        stream_id = "stream-drop-test"
        self._session(stream_id)
        try:
            with (
                patch(
                    "app.services.hil.bridge.stream_manager.publish_chunk",
                    new=AsyncMock(),
                ),
                patch("app.services.hil.bridge._schedule_pending_notification"),
            ):
                await publish_ledger_request(
                    GatedApproval(
                        approval_id="ap_drop",
                        stream_id=stream_id,
                        user_id="u1",
                        conversation_id="conv-1",
                        tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="c1", args={"to": "b@x"}),
                        summary="Send it",
                        integration_name="gmail",
                    ),
                )
            row = MagicMock()
            row.approval_id = "ap_drop"
            row.proposing_run_id = stream_id
            with (
                patch.object(ledger_decide, "_persist_decision_status", new=AsyncMock()),
                patch.object(ledger_decide, "_broadcast_decision", new=AsyncMock()),
            ):
                await ledger_decide.publish_ledger_revocation(row)
            from app.agents.core.background.session import get_session

            assert get_session(stream_id).tool_events == []
        finally:
            self._teardown(stream_id)


@pytest.mark.unit
class TestFlushHeldCards:
    """Run end pushes held PENDING cards live — without this the open client never renders them until a full refresh re-fetches messages."""

    def _held_frame(self, approval_id: str = "ap_hold") -> dict[str, object]:
        return {
            "tool_data": {
                "tool_name": "approval_request",
                "data": {"approval_id": approval_id, "status": "pending"},
            },
            "_held_approval": True,
        }

    def _session_with_held(self, stream_id: str, approval_id: str = "ap_hold"):
        from app.agents.core.background.session import RunKind, create_session

        session = create_session(stream_id, RunKind.LIVE)
        session.tool_events.append(self._held_frame(approval_id))
        return session

    def _teardown(self, stream_id: str) -> None:
        from app.agents.core.background.session import teardown_session

        teardown_session(stream_id)

    async def test_pending_held_frame_publishes_once_then_clears_marker(self) -> None:
        from app.services.hil import bridge

        stream_id = "stream-flush-test"
        self._session_with_held(stream_id)
        row = MagicMock()
        row.approval_id = "ap_hold"
        row.user_id = "u1"
        row.conversation_id = "conv-1"
        row.summary = "Send it"
        row.state = "pending"
        try:
            with (
                patch.object(bridge, "approval_ledger_repository") as repo,
                patch.object(bridge.stream_manager, "publish_chunk", new=AsyncMock()) as chunk,
                patch.object(bridge, "_schedule_pending_notification") as notify,
            ):
                repo.get_by_approval_id = AsyncMock(return_value=row)
                assert await bridge.flush_held_approval_cards(stream_id) == 1
                assert await bridge.flush_held_approval_cards(stream_id) == 0
            chunk.assert_awaited_once()
            notify.assert_called_once_with("u1", "conv-1", "ap_hold", "Send it")
        finally:
            self._teardown(stream_id)

    async def test_non_pending_held_frame_dropped_unseen(self) -> None:
        from app.services.hil import bridge

        stream_id = "stream-flush-drop-test"
        session = self._session_with_held(stream_id)
        row = MagicMock()
        row.state = "revoked"
        try:
            with (
                patch.object(bridge, "approval_ledger_repository") as repo,
                patch.object(bridge.stream_manager, "publish_chunk", new=AsyncMock()) as chunk,
                patch.object(bridge, "_schedule_pending_notification") as notify,
            ):
                repo.get_by_approval_id = AsyncMock(return_value=row)
                assert await bridge.flush_held_approval_cards(stream_id) == 0
            chunk.assert_not_awaited()
            notify.assert_not_called()
            assert session.tool_events == []
        finally:
            self._teardown(stream_id)

    async def test_no_session_is_zero(self) -> None:
        from app.services.hil import bridge

        assert await bridge.flush_held_approval_cards("stream-missing") == 0
