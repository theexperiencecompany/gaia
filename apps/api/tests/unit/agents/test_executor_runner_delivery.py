"""Unit tests for background-executor message delivery.

Two invariants, both owned by result_delivery.py:

* a background result is delivered over EXACTLY ONE transport, chosen by the
  conversation's own source — bot conversations to their platform, everything
  else over WebSocket — and the message is always persisted;
* a HIL-resumed run MERGES onto the original turn's bot message rather than
  appending a rival one, and the merge never duplicates a message, drops cards
  the user already saw, or resurrects an approval they already decided.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
from prometheus_client import REGISTRY
import pytest

from app.agents.core.background import executor_runner as er, result_delivery as rd
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
)
from app.constants.executor import (
    EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE,
    EXECUTOR_NARRATION_FAILED_MESSAGE,
)
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource, MessageModel, ToolDataEntry
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.models.message_models import ReplyToMessageData
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents
from shared.py.wide_events import log
from tests.helpers import captured_wide_event


def _run(
    kind: RunKind = RunKind.LIVE,
    *,
    stream_id: str = "",
    task_id: str | None = None,
    bot_message_id: str | None = None,
    workflow: bool = False,
) -> ExecutorRun:
    """Build a run context for delivery tests (defaults: live, non-workflow)."""
    run = ExecutorRun(
        stream_id=stream_id,
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id="user-1"),
        kind=kind,
        task_id=task_id,
        user_message_id=None,
        bot_message_id=bot_message_id,
        workflow_id="wf-1" if workflow else None,
        workflow_title="Morning digest" if workflow else "",
        active_todo_id="todo-9" if workflow else None,
    )
    return run


#: One executor tool card, in the shape ``_finalize_executor_run`` snapshots off
#: the session and hands to delivery.
CARDS: list[ToolDataEntry] = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]


async def _deliver(
    conv_source,
    *,
    comms_text="result text",
    result_text="raw",
    result_type="final",
    platform_delivered=True,
    task_id=None,
):
    """Run deliver_result with all I/O boundaries mocked.

    Returns (save_mock, platform_mock, ws_mock) for assertions. The real
    is_bot_platform routing logic runs unmocked against conv_source.
    """
    with (
        patch.object(
            rd, "narrate_executor_result", new_callable=AsyncMock, return_value=comms_text
        ),
        patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
        patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
        patch.object(
            rd, "_get_conversation_source", new_callable=AsyncMock, return_value=conv_source
        ),
        patch.object(
            rd,
            "deliver_message_to_platform",
            new_callable=AsyncMock,
            return_value=platform_delivered,
        ) as platform,
        patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
    ):
        await rd.deliver_result(
            _run(task_id=task_id),
            result_text=result_text,
            result_type=result_type,
            tool_data=None,
        )
    return save, platform, ws


class TestBotFollowUpsNeverGateTheAnswer:
    """A bot user waited 5 to 8 s for follow-up suggestions the platform never shows."""

    async def _deliver_to_telegram(self, *, delivered: bool):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[]
            ) as inline,
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.TELEGRAM,
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=delivered
            ) as platform,
            patch.object(rd, "_spawn_deferred_follow_ups") as deferred,
        ):
            await rd.deliver_result(_run(), result_text="raw", result_type="final", tool_data=None)
        return inline, platform, deferred

    async def test_the_answer_is_sent_before_any_follow_up_is_generated(self) -> None:
        inline, platform, deferred = await self._deliver_to_telegram(delivered=True)

        inline.assert_not_awaited()
        platform.assert_awaited_once()
        deferred.assert_called_once()

    async def test_an_undelivered_answer_spawns_no_follow_ups(self) -> None:
        _, _, deferred = await self._deliver_to_telegram(delivered=False)

        deferred.assert_not_called()


class TestTheBotAnswersFollowUpsBelongToIt:
    """The follow-ups generated after a bot delivery attach to the message the user got."""

    async def _deliver_quoting_run_to_telegram(self):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.TELEGRAM,
            ),
            patch.object(
                rd,
                "_lookup_user_message_content",
                new_callable=AsyncMock,
                return_value="what I asked",
            ),
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ),
            patch.object(rd, "_spawn_deferred_follow_ups") as deferred,
        ):
            await rd.deliver_result(
                _quoting_run(), result_text="raw", result_type="final", tool_data=CARDS
            )
        return save.await_args.args[0].messages[0], deferred.call_args.kwargs

    async def test_they_are_generated_for_the_saved_message_and_its_cards(self) -> None:
        saved, follow_ups = await self._deliver_quoting_run_to_telegram()

        assert follow_ups["bot_message"].message_id == saved.message_id
        assert follow_ups["bot_message"].response == "voiced"
        assert follow_ups["tool_data"] == CARDS
        assert follow_ups["result_type"] == "final"

    async def test_they_go_to_the_same_owner_and_quote(self) -> None:
        _saved, follow_ups = await self._deliver_quoting_run_to_telegram()

        assert follow_ups["target"] == _target()


class TestAWorkflowAnswerCarriesItsFollowUpsInline:
    """A workflow run has no one waiting on a live stream, so suggestions ride on the saved message."""

    async def test_the_saved_message_holds_the_generated_follow_ups(self) -> None:
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd,
                "_safe_inline_follow_ups",
                new_callable=AsyncMock,
                return_value=["Run it again tomorrow"],
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock),
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock),
        ):
            await rd.deliver_result(
                _run(workflow=True), result_text="done", result_type="final", tool_data=None
            )

        saved = save.await_args.args[0].messages[0]
        assert saved.follow_up_actions == ["Run it again tomorrow"]


class TestDeliverResultRouting:
    @pytest.mark.parametrize(
        "src",
        [
            ConversationSource.WHATSAPP,
            ConversationSource.SLACK,
            ConversationSource.DISCORD,
            ConversationSource.TELEGRAM,
        ],
    )
    async def test_bot_conversation_delivers_to_platform_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        platform.assert_awaited_once()
        assert platform.await_args.args[0] == src  # routed to the conversation's platform
        assert platform.await_args.args[2] == "result text"  # the comms-generated text
        ws.assert_not_awaited()  # exclusive: no WebSocket fan-out for bots
        save.assert_awaited_once()  # always persisted to history

    @pytest.mark.parametrize("src", [ConversationSource.WEB, ConversationSource.MOBILE, None])
    async def test_non_bot_conversation_broadcasts_over_websocket_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        ws.assert_awaited_once()
        platform.assert_not_awaited()  # exclusive: no platform send for web/mobile/system
        save.assert_awaited_once()

    async def test_websocket_payload_carries_conversation_and_message(self) -> None:
        _save, _platform, ws = await _deliver(ConversationSource.WEB)
        event = ws.await_args.args[1]
        assert event["type"] == "conversation.new_message"
        assert event["conversation_id"] == "conv-1"
        assert event["message"]["response"] == "result text"

    async def test_the_save_is_attributed_to_the_runs_owner(self) -> None:
        """update_messages scopes the write by user — an unattributed save lands on nobody's conversation."""
        save, _platform, _ws = await _deliver(ConversationSource.WEB)

        assert save.await_args.kwargs["user"] == AuthenticatedUser(user_id="user-1")

    async def test_never_leaks_raw_executor_text_when_comms_unavailable(self) -> None:
        # The executor's terminal text is internal monologue, so a narration
        # failure delivers a notice instead of publishing it verbatim.
        _save, platform, _ws = await _deliver(
            ConversationSource.WHATSAPP,
            comms_text="",
            result_text="Let me find the delete tool.",
        )
        delivered = platform.await_args.args[2]
        assert delivered == EXECUTOR_NARRATION_FAILED_MESSAGE
        assert "delete tool" not in delivered

    async def test_never_leaks_a_raw_exception_when_error_narration_fails(self) -> None:
        # The error path carries str(e) from executor_runner, not curated copy.
        _save, platform, _ws = await _deliver(
            ConversationSource.WHATSAPP,
            comms_text="",
            result_text="KeyError('composio_auth')",
            result_type="error",
        )
        delivered = platform.await_args.args[2]
        assert delivered == EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE
        assert "KeyError" not in delivered


class TestDeliveryOutcomeIsOnTheWideEvent:
    """A finished run can still fail delivery silently — the delivery verdict must be ON the wide event, not a bare INFO line.

    Otherwise a Telegram turn ends in silence with a green wide event.
    """

    @pytest.fixture(autouse=True)
    def _fresh_wide_event(self) -> None:
        log.reset()

    async def test_a_failed_platform_send_is_recorded_as_undelivered(self) -> None:
        await _deliver(ConversationSource.TELEGRAM, platform_delivered=False)

        assert log.get()["result_delivery"]["delivered"] is False
        assert log.get()["result_delivery"]["transport"] == "platform"
        assert log.get()["result_delivery"]["source"] == "telegram"

    async def test_a_failed_platform_send_raises_the_events_level(self) -> None:
        """delivered: false is only half the signal; the drop must also raise the event's severity to error."""
        await _deliver(ConversationSource.TELEGRAM, platform_delivered=False)

        errors = log.get()["errors"]
        assert len(errors) == 1
        assert "NOT delivered" in errors[0]["msg"]
        assert errors[0]["conversation_id"] == "conv-1"

    async def test_the_undelivered_error_names_the_message_task_and_route(self) -> None:
        """The undelivered error must name the message id, task id, and route — without them nothing is actionable."""
        await _deliver(ConversationSource.TELEGRAM, platform_delivered=False, task_id="task-1")

        (error,) = log.get()["errors"]
        assert error["task_id"] == "task-1"
        assert error["conversation_source"] == "telegram"
        assert error["transport"] == "platform"
        assert error["message_id"], "the saved message must be identified"

    async def test_the_result_type_is_on_the_delivery_namespace(self) -> None:
        """An errored run and a finished one deliver through the same path; result_type is what separates them."""
        await _deliver(ConversationSource.TELEGRAM)

        assert log.get()["result_delivery"]["result_type"] == "final"

    async def test_a_successful_send_is_recorded_as_delivered_with_no_error(self) -> None:
        await _deliver(ConversationSource.TELEGRAM)

        assert log.get()["result_delivery"]["delivered"] is True
        assert "errors" not in log.get()

    async def test_the_narration_fallback_is_visible_separately_from_delivery(self) -> None:
        """Comms failing and the send failing are different faults with the same symptom, so narrated is its own field."""
        await _deliver(ConversationSource.TELEGRAM, comms_text="", result_text="raw output")

        assert log.get()["result_delivery"]["narrated"] is False
        assert log.get()["result_delivery"]["text_length"] == len(EXECUTOR_NARRATION_FAILED_MESSAGE)
        assert log.get()["result_delivery"]["delivered"] is True


class TestDeliveryOrigin:
    """The provenance frame recorded into a platform thread when a workflow result is delivered there.

    It is how a later turn backtracks to the source, so the title, both
    machine ids, and their absence cases are load-bearing.
    """

    def test_names_the_title_and_both_ids(self) -> None:
        run = _run(workflow=True)
        assert rd._delivery_origin(run) == (
            'workflow "Morning digest" (id wf-1), tracked todo (id todo-9)'
        )

    def test_an_untitled_workflow_has_no_quote_fragment(self) -> None:
        run = _run(workflow=True)
        run = replace(run, workflow_title="", active_todo_id=None)
        assert rd._delivery_origin(run) == "workflow (id wf-1)"

    def test_an_untracked_run_has_no_todo_clause(self) -> None:
        run = _run(workflow=True)
        run = replace(run, active_todo_id=None)
        assert rd._delivery_origin(run) == 'workflow "Morning digest" (id wf-1)'


class TestWorkflowResultReachesThePlatformDelivery:
    """A finished workflow run hands its result to the platform-delivery path with the run's own owner and provenance.

    A wrong user_id would deliver into a stranger's chats, a wrong origin
    would orphan the trail.
    """

    async def test_delivery_carries_the_runs_owner_and_origin(self) -> None:
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="done"
            ),
            patch.object(rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock) as deliver,
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock) as notify,
        ):
            await rd.deliver_result(
                _run(workflow=True), result_text="done", result_type="final", tool_data=None
            )

        deliver.assert_awaited_once()
        kwargs = deliver.await_args.kwargs
        assert kwargs["user"] == AuthenticatedUser(user_id="user-1")
        assert kwargs["user_id"] == "user-1"
        assert kwargs["origin"] == ('workflow "Morning digest" (id wf-1), tracked todo (id todo-9)')
        notify.assert_awaited_once()  # the in-app badge still fires alongside


class TestGetConversationSource:
    """The authoritative routing key: the conversation's persisted source.

    Coercion of a stored string into the enum now lives in the repository's
    get_source (covered by the repository contract tests); here we assert the
    delivery wrapper passes it through, scopes by owner, and fails soft.
    """

    async def test_returns_source_from_repository(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WHATSAPP
            src = await rd._get_conversation_source("conv-1", "user-1")
        assert src is ConversationSource.WHATSAPP

    async def test_query_is_scoped_to_conversation_and_owner(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WEB
            await rd._get_conversation_source("conv-1", "user-1")
        # must be scoped by BOTH conversation_id and user_id (no cross-user read)
        assert get.await_args.args[0] == "conv-1"
        assert get.await_args.kwargs["user_id"] == "user-1"

    async def test_missing_conversation_returns_none(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = None
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_db_error_returns_none(self) -> None:
        with patch.object(rd.conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.side_effect = RuntimeError("mongo down")
            assert await rd._get_conversation_source("conv-1", "user-1") is None


class TestPersistCancelledRun:
    """Cancelled self-owning runs: cards-only persist, no narration, no re-push.

    These pin the "stop the stream → cards survive" fix. The cards were already
    streamed live, so the persisted copy must reconcile with the frontend
    placeholder by message_id == task_id and must NOT go out over the
    WebSocket again.
    """

    async def test_persists_cards_only_message_keyed_by_task_id(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock) as narrate,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            await rd.persist_cancelled_run(run, CARDS)

        save.assert_awaited_once()
        saved = save.await_args.args[0].messages[0]
        assert saved.message_id == "task-9"  # reconciles with the placeholder by id
        assert saved.response == ""  # cards-only: comms never narrated this turn
        assert saved.tool_data and saved.tool_data[0]["tool_name"] == "tool_calls_data"
        narrate.assert_not_awaited()  # the run was stopped — no re-voicing
        ws.assert_not_awaited()  # no re-broadcast of already-streamed data

    async def test_no_cards_writes_nothing(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run, [])

        save.assert_not_awaited()

    async def test_save_failure_is_swallowed(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        with patch.object(
            rd, "update_messages", new_callable=AsyncMock, side_effect=RuntimeError("mongo down")
        ):
            await rd.persist_cancelled_run(run, CARDS)  # must not raise


def _persist_count(op: str) -> float:
    return REGISTRY.get_sample_value("delivery_persist_seconds_count", {"op": op}) or 0.0


def _narration_count(status: str) -> float:
    return REGISTRY.get_sample_value("delivery_narration_seconds_count", {"status": status}) or 0.0


class TestDeliveryLatency:
    """Delivery splits narration (LLM) from persistence (Mongo)."""

    async def test_cancelled_persist_records_span_without_narration(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_lat", task_id="task-lat")
        before = _persist_count("cancelled_cards")
        narration_before = _narration_count("success")

        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock) as narrate,
        ):
            await rd.persist_cancelled_run(run, CARDS)

        narrate.assert_not_awaited()
        assert _persist_count("cancelled_cards") == before + 1
        assert _narration_count("success") == narration_before

    async def test_narration_records_span(self) -> None:
        before = _narration_count("success")
        with (
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock, return_value="v"),
            patch.object(rd, "_approval_outcomes_note", new_callable=AsyncMock, return_value=""),
        ):
            await rd._narrate_result(_run(), "raw", "final", "")
        assert _narration_count("success") == before + 1

    async def test_save_bot_message_records_span(self) -> None:
        before = _persist_count("save_bot_message")
        bot_message = MessageModel(type="bot", response="hi", date="2026-01-01")
        with patch.object(rd, "update_messages", new_callable=AsyncMock):
            assert await rd._save_bot_message("conv-1", {"user_id": "user-1"}, bot_message) is True
        assert _persist_count("save_bot_message") == before + 1

    async def test_cancelled_persist_records_exact_seconds(self) -> None:
        # Pinned clock: the persisted sample must be the elapsed subtraction in
        # SECONDS. A sign error (end + start) would record 40.75 here.
        run = _run(RunKind.QUEUED, stream_id="queued_lat2", task_id="task-lat2")
        labels = {"op": "cancelled_cards"}
        before = REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) or 0.0
        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd.time, "perf_counter", side_effect=[20.0, 20.75]),
        ):
            await rd.persist_cancelled_run(run, CARDS)
        assert REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) == before + 0.75

    async def test_save_bot_message_records_exact_seconds(self) -> None:
        labels = {"op": "save_bot_message"}
        before = REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) or 0.0
        bot_message = MessageModel(type="bot", response="hi", date="2026-01-01")
        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd.time, "perf_counter", side_effect=[7.0, 7.25]),
        ):
            assert await rd._save_bot_message("conv-1", {"user_id": "user-1"}, bot_message) is True
        assert REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) == before + 0.25

    async def test_narration_records_exact_seconds(self) -> None:
        labels = {"status": "success"}
        before = REGISTRY.get_sample_value("delivery_narration_seconds_sum", labels) or 0.0
        with (
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock, return_value="v"),
            patch.object(rd, "_approval_outcomes_note", new_callable=AsyncMock, return_value=""),
            patch.object(rd.time, "perf_counter", side_effect=[3.0, 3.5]),
        ):
            await rd._narrate_result(_run(), "raw", "final", "")
        assert REGISTRY.get_sample_value("delivery_narration_seconds_sum", labels) == before + 0.5

    async def test_narration_fallback_is_recorded_under_the_fallback_status(self) -> None:
        # comms unavailable -> the notice is delivered, and the sample is
        # labelled "fallback". A recased or renamed status would silently split
        # the fallback rate across two series.
        run = _run(RunKind.QUEUED, stream_id="queued_lat3", task_id="task-lat3")
        count_labels = {"status": "fallback"}
        sum_labels = {"status": "fallback"}
        count_before = (
            REGISTRY.get_sample_value("delivery_narration_seconds_count", count_labels) or 0.0
        )
        sum_before = REGISTRY.get_sample_value("delivery_narration_seconds_sum", sum_labels) or 0.0
        with (
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock, return_value=""),
            patch.object(rd, "_approval_outcomes_note", new_callable=AsyncMock, return_value=""),
            patch.object(rd.time, "perf_counter", side_effect=[3.0, 3.5]),
        ):
            assert await rd._narrate_result(run, "raw fallback text", "final", "") == (
                EXECUTOR_NARRATION_FAILED_MESSAGE
            )
        assert (
            REGISTRY.get_sample_value("delivery_narration_seconds_count", count_labels)
            == count_before + 1
        )
        assert (
            REGISTRY.get_sample_value("delivery_narration_seconds_sum", sum_labels)
            == sum_before + 0.5
        )


class TestDeliverResultToolDataOwnership:
    """deliver_result attaches caller-snapshotted cards and keys queued messages on task_id for dedup.

    A live run arrives with tool_data=None — its cards belong to the comms
    stream, and a second copy here would render every card twice.
    """

    async def _deliver_with_cards(self, run: ExecutorRun, tool_data: list[ToolDataEntry] | None):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd, "_lookup_user_message_content", new_callable=AsyncMock, return_value=""
            ),
        ):
            await rd.deliver_result(run, "raw result", "final", tool_data=tool_data)
        return save, ws

    async def test_queued_run_attaches_cards_and_uses_task_id(self) -> None:
        run = _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9")

        save, ws = await self._deliver_with_cards(run, CARDS)

        saved = save.await_args.args[0].messages[0]
        assert saved.message_id == "task-9"
        assert saved.tool_data and saved.tool_data[0]["tool_name"] == "tool_calls_data"
        ws_message = ws.await_args.args[1]["message"]
        assert ws_message["tool_data"] == saved.tool_data
        assert ws_message["task_id"] == "task-9"

    async def test_the_message_is_saved_as_the_runs_own_user(self) -> None:
        """A background run has no request session; the save is authorized by the user carried on the run."""
        run = _run()

        save, _ws = await self._deliver_with_cards(run, None)

        assert save.await_args.kwargs["user"] == AuthenticatedUser(user_id="user-1")

    async def test_live_run_never_self_attaches_cards(self) -> None:
        """The comms stream owns a live run's cards, so its snapshot is None — delivery must not invent tool_data."""
        run = _run(RunKind.LIVE, stream_id="live_s1", task_id="task-9")

        save, ws = await self._deliver_with_cards(run, None)

        saved = save.await_args.args[0].messages[0]
        assert not saved.tool_data
        assert saved.message_id != "task-9"  # no placeholder to reconcile with
        assert "tool_data" not in ws.await_args.args[1]["message"]

    async def test_live_run_with_bot_message_id_still_appends_a_fresh_message(self) -> None:
        """bot_message_id alone must not route delivery down the HIL-merge path, which races the comms stream's save."""
        run = _run(RunKind.LIVE, stream_id="live_s2", task_id="task-10", bot_message_id="ack-msg-1")
        with patch.object(rd, "_merge_resumed_result", new_callable=AsyncMock) as merge:
            save, ws = await self._deliver_with_cards(run, None)

        merge.assert_not_awaited()
        saved = save.await_args.args[0].messages[0]
        assert saved.message_id != "ack-msg-1"
        assert saved.message_id != "task-10"

    async def test_save_failure_prevents_any_transport_push(self) -> None:
        """MongoDB is the source of truth — a message that failed to persist must never be pushed."""
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(
                rd,
                "update_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock) as source,
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            await rd.deliver_result(run, "raw", "final", tool_data=None)

        # _get_conversation_source is now called before update_messages to
        # determine the delivery path; it IS called even when save fails.
        source.assert_awaited_once()
        platform.assert_not_awaited()
        ws.assert_not_awaited()

    async def test_error_results_get_no_follow_up_suggestions(self) -> None:
        run = _run()
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="it broke"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock) as follow_ups,
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
        ):
            await rd.deliver_result(run, "traceback...", "error", tool_data=None)

        follow_ups.assert_not_awaited()


# ---------------------------------------------------------------------------
# run_executor_background lifecycle analytics
# ---------------------------------------------------------------------------


class TestRunLifecycleAnalytics:
    """AGENT_RUN_STARTED/COMPLETED/FAILED around the executor run boundary."""

    async def _run_lifecycle(
        self,
        result_text: str,
        result_type: str,
        *,
        task_id: str | None = "task-1",
        user_id: str | None = "user-1",
    ):
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            # user_id=None models a run whose user dict carries no id at all.
            user=AuthenticatedUser(user_id=user_id or ""),
            kind=RunKind.LIVE,
            task_id=task_id,
            user_message_id=None,
        )
        with (
            patch("app.agents.core.background.executor_runner.capture_event") as mock_capture,
            patch.object(
                er,
                "_execute_executor",
                new_callable=AsyncMock,
                return_value=_ExecutorResult(result_text, result_type),
            ),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": user_id})
        return mock_capture

    async def test_started_and_completed_on_final(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final")

        events = [c.args[1] for c in mock_capture.call_args_list]
        assert events == [
            AnalyticsEvents.AGENT_RUN_STARTED,
            AnalyticsEvents.AGENT_RUN_COMPLETED,
        ]
        expected_props = {
            "agent": "executor",
            "mode": "background",
            "conversation_id": "conv-1",
            "task_id": "task-1",
        }
        assert mock_capture.call_args_list[0].args[0] == "user-1"
        assert mock_capture.call_args_list[0].args[2] == expected_props
        # The TERMINAL event needs the same scrutiny as the opening one: it was
        # asserted only by name, so its user id and payload could both go null
        # without a test noticing.
        assert mock_capture.call_args_list[1].args[0] == "user-1"
        terminal_props = mock_capture.call_args_list[1].args[2]
        assert terminal_props["agent"] == "executor"
        assert terminal_props["mode"] == "background"
        assert terminal_props["conversation_id"] == "conv-1"
        assert terminal_props["task_id"] == "task-1"
        assert terminal_props["queued"] is False
        assert terminal_props["executor_active_ms"] >= 0.0

    async def test_failed_on_error_result(self) -> None:
        mock_capture = await self._run_lifecycle("it broke", "error")

        events = [c.args[1] for c in mock_capture.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_STARTED, AnalyticsEvents.AGENT_RUN_FAILED]
        assert mock_capture.call_args_list[1].args[0] == "user-1"
        terminal_props = mock_capture.call_args_list[1].args[2]
        assert terminal_props["agent"] == "executor"
        assert terminal_props["task_id"] == "task-1"
        assert terminal_props["queued"] is False
        assert terminal_props["executor_active_ms"] >= 0.0

    async def test_a_run_with_no_user_id_captures_nothing(self) -> None:
        """run.user with no id must produce no events at all — the guard relies on a "" default staying falsy."""
        mock_capture = await self._run_lifecycle("done", "final", user_id=None)

        mock_capture.assert_not_called()

    async def test_paused_run_has_no_terminal_event(self) -> None:
        """A HIL pause is not a terminal outcome — the resume re-enters and captures its own STARTED."""
        mock_capture = await self._run_lifecycle("", "paused")

        events = [c.args[1] for c in mock_capture.call_args_list]
        assert events == [AnalyticsEvents.AGENT_RUN_STARTED]

    async def test_no_user_id_skips_events(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final", user_id="")
        mock_capture.assert_not_called()


class TestDeliverResultHilResume:
    """A HIL-resumed run merges its result onto the ORIGINAL live turn's message in place, not a rival append.

    The same class of trap _persist_follow_up_actions already guards against for follow-ups.
    """

    async def _deliver_resumed(self, run: ExecutorRun, *, existing_tool_data=None, tool_data=None):
        existing = MessageModel(type="bot", response="old text", date="2026-01-01")
        existing.tool_data = existing_tool_data
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="new voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new_callable=AsyncMock,
                return_value=existing,
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new_callable=AsyncMock,
                return_value=True,
            ) as set_resp,
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new_callable=AsyncMock,
                return_value=True,
            ) as set_td,
        ):
            result = await rd.deliver_result(run, "raw result", "final", tool_data=tool_data)
        return result, save, ws, get_msg, set_resp, set_td

    async def test_merges_onto_original_message_instead_of_appending(self) -> None:
        run = _run(
            RunKind.QUEUED,
            stream_id="queued_s1",
            task_id="task-resume-1",
            bot_message_id="orig-msg-1",
        )

        (text, message_id), save, ws, get_msg, set_resp, set_td = await self._deliver_resumed(
            run, tool_data=CARDS
        )

        assert message_id == "orig-msg-1"  # reconciles onto the ORIGINAL message, not task_id
        save.assert_not_awaited()  # never $push's a rival array element

        # Read twice on purpose: once by _approval_outcomes_note to ground the
        # narration in this run's decided gates, once by the merge itself. What
        # matters is that BOTH target the original message, never the task_id.
        assert get_msg.await_count == 2
        assert all(call.args[1] == "orig-msg-1" for call in get_msg.await_args_list)
        assert get_msg.await_args.args == ("conv-1", "orig-msg-1")

        set_resp.assert_awaited_once()
        assert set_resp.await_args.kwargs["message_id"] == "orig-msg-1"
        assert set_resp.await_args.kwargs["response"] == "new voiced"

        set_td.assert_awaited_once()
        assert set_td.await_args.kwargs["message_id"] == "orig-msg-1"

        # A live task_id-keyed placeholder DOES exist for queued-kind runs
        # (real queue pops AND resumes), so task_id must still be emitted —
        # otherwise the frontend's placeholder is orphaned forever.
        ws_message = ws.await_args.args[1]["message"]
        assert ws_message["message_id"] == "orig-msg-1"
        assert ws_message["task_id"] == "task-resume-1"

    async def test_merged_tool_data_carries_original_plus_new_cards(self) -> None:
        run = _run(
            RunKind.QUEUED,
            stream_id="queued_s1",
            task_id="task-resume-1",
            bot_message_id="orig-msg-1",
        )
        existing_cards = [{"tool_name": "old_tool", "data": {}}]

        (_text, _mid), _save, ws, _get_msg, _set_resp, _set_td = await self._deliver_resumed(
            run, existing_tool_data=existing_cards, tool_data=CARDS
        )

        # A WebSocket push replaces the client's stored message wholesale, so
        # dropping either half here would erase real cards from the user's view.
        ws_message = ws.await_args.args[1]["message"]
        tool_names = [c["tool_name"] for c in ws_message["tool_data"]]
        assert "old_tool" in tool_names
        assert "tool_calls_data" in tool_names  # the resumed run's new card

    async def test_missing_original_message_falls_back_to_a_fresh_append(self) -> None:
        """The approved action already RAN; a deleted original bubble must not discard its report — re-key to a fresh id."""
        run = _run(RunKind.QUEUED, task_id="task-resume-1", bot_message_id="orig-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd.conversation_repository, "get_message", new_callable=AsyncMock, return_value=None
            ),
            patch.object(rd, "log") as mock_log,
        ):
            text, message_id = await rd.deliver_result(run, "raw", "final", tool_data=None)

        assert text == "voiced"
        save.assert_awaited_once()
        saved = save.await_args.args[0].messages[0]
        # A fresh REAL id, NOT the dead original and NOT the task id — nothing
        # on the client reconciles against either for this fallback message.
        assert saved.message_id == message_id
        assert saved.message_id != "orig-msg-1"
        UUID(saved.message_id)
        ws.assert_awaited_once()
        # The fallback is loud, and names the message it could not merge onto.
        # Exact tail, not a substring — a mangled message still CONTAINS the
        # substring, so only equality can catch it.
        warning = next(
            c for c in mock_log.warning.call_args_list if "original_message_id" in c.kwargs
        )
        assert warning.args[0].endswith(
            "original message unavailable, appending a fresh one instead"
        )
        assert warning.kwargs["original_message_id"] == "orig-msg-1"
        assert warning.kwargs["conversation_id"] == run.conversation_id


def _approval_card(approval_id: str, status: str, **extra) -> dict:
    return {
        "tool_name": APPROVAL_REQUEST_TOOL_NAME,
        "data": {"approval_id": approval_id, "status": status, **extra},
    }


def _record(approval_id: str, status: HILApprovalStatus, tool_name: str = "SEND_GMAIL"):
    return HILApprovalRecord(
        approval_id=approval_id,
        user_id="user-1",
        conversation_id="conv-1",
        stream_id="stream-1",
        tool_name=tool_name,
        status=status,
        decided_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
    )


class TestApprovalId:
    """The key every merge decision is made on.

    Reading it off the wrong kind of card silently turns an ordinary tool
    card into an approval and lets the upsert overwrite it.
    """

    def test_an_approval_card_yields_its_id(self) -> None:
        assert rd._approval_id(_approval_card("a1", "pending")) == "a1"

    def test_an_ordinary_tool_card_is_not_an_approval(self) -> None:
        entry = {"tool_name": "web_search_tool", "data": {"approval_id": "a1"}}
        assert rd._approval_id(entry) is None

    def test_a_non_dict_payload_is_not_an_approval(self) -> None:
        assert rd._approval_id({"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": "a1"}) is None

    def test_a_non_string_id_is_rejected(self) -> None:
        entry = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {"approval_id": 17}}
        assert rd._approval_id(entry) is None

    def test_a_card_with_no_id_at_all_is_rejected(self) -> None:
        entry = {"tool_name": APPROVAL_REQUEST_TOOL_NAME, "data": {}}
        assert rd._approval_id(entry) is None


class TestMergeToolData:
    """The resumed stream replays the gate-time PENDING frame after the decision already landed.

    Appending blindly resurrects a decided card.
    """

    def test_ordinary_cards_append_after_the_existing_ones(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {}}]
        new = [{"tool_name": "new_tool", "data": {}}]

        merged = rd._merge_tool_data(existing, new)

        assert [e["tool_name"] for e in merged] == ["old_tool", "new_tool"]

    def test_an_unseen_approval_appends(self) -> None:
        merged = rd._merge_tool_data([], [_approval_card("a1", "pending")])

        assert merged == [_approval_card("a1", "pending")]

    def test_a_replayed_pending_never_downgrades_a_settled_decision(self) -> None:
        """Regression: the user decided, then a replay put the pending card back and re-offered approve/decline."""
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")], [_approval_card("a1", "pending")]
        )

        assert len(merged) == 1, "the replay duplicated the card instead of upserting"
        assert merged[0]["data"]["status"] == "approved"

    @pytest.mark.parametrize(
        "settled", ["approved", "denied", "timeout", "abandoned", "auto_approved"]
    )
    def test_every_settled_status_survives_a_pending_replay(self, settled: str) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", settled)], [_approval_card("a1", "pending")]
        )

        assert merged[0]["data"]["status"] == settled

    def test_a_settled_decision_overwrites_a_pending_card(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "pending")], [_approval_card("a1", "denied")]
        )

        assert len(merged) == 1
        assert merged[0]["data"]["status"] == "denied"

    def test_a_later_settled_frame_replaces_an_earlier_one(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved", note="first")],
            [_approval_card("a1", "approved", note="second")],
        )

        assert len(merged) == 1
        assert merged[0]["data"]["note"] == "second"

    def test_different_approvals_do_not_collide(self) -> None:
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")],
            [_approval_card("a2", "pending"), _approval_card("a1", "pending")],
        )

        by_id = {e["data"]["approval_id"]: e["data"]["status"] for e in merged}
        assert by_id == {"a1": "approved", "a2": "pending"}

    def test_an_approval_added_in_this_batch_is_upserted_not_duplicated(self) -> None:
        """The index has to learn about ids appended during the same pass, or a same-batch card duplicates itself."""
        merged = rd._merge_tool_data(
            [], [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        assert len(merged) == 1
        assert merged[0]["data"]["status"] == "approved"

    def test_the_existing_list_is_not_mutated(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {}}]

        rd._merge_tool_data(existing, [{"tool_name": "new_tool", "data": {}}])

        assert [e["tool_name"] for e in existing] == ["old_tool"]


class TestReconcileApprovalStatuses:
    """A decision's resolved frame may never reach the stream this delivery drains — the record is the source of truth."""

    async def test_a_stale_status_is_corrected_from_the_record(self) -> None:
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.APPROVED)),
        ):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "pending")])

        assert out[0]["data"]["status"] == HILApprovalStatus.APPROVED

    async def test_the_input_entry_is_not_mutated(self) -> None:
        entry = _approval_card("a1", "pending")
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.DENIED)),
        ):
            await rd._reconcile_approval_statuses([entry])

        assert entry["data"]["status"] == "pending", "reconciling mutated the caller's entry"

    async def test_an_ordinary_card_is_passed_through_untouched(self) -> None:
        entry = {"tool_name": "web_search_tool", "data": {"status": "pending"}}
        with patch.object(rd, "get_approval", new=AsyncMock()) as get:
            out = await rd._reconcile_approval_statuses([entry])

        assert out == [entry]
        get.assert_not_awaited(), "an ordinary card triggered an approvals lookup"

    async def test_a_missing_record_leaves_the_card_alone(self) -> None:
        with patch.object(rd, "get_approval", new=AsyncMock(return_value=None)):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "pending")])

        assert out[0]["data"]["status"] == "pending"

    async def test_an_already_correct_status_is_left_as_is(self) -> None:
        with patch.object(
            rd,
            "get_approval",
            new=AsyncMock(return_value=_record("a1", HILApprovalStatus.APPROVED)),
        ):
            out = await rd._reconcile_approval_statuses([_approval_card("a1", "approved")])

        assert out[0]["data"]["status"] == "approved"


class TestApprovalOutcomesNote:
    """Ground truth handed to the narrator so it stops telling the user an action is still pending after they decided."""

    async def test_no_original_message_means_no_note(self) -> None:
        assert await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id=None)) == ""

    async def test_a_message_without_cards_means_no_note(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        with patch.object(
            rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )

    async def test_a_decided_approval_is_reported_by_its_outcome(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = [_approval_card("a1", "pending")]
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ),
            patch.object(
                rd,
                "get_approval",
                new=AsyncMock(return_value=_record("a1", HILApprovalStatus.DENIED)),
            ),
        ):
            note = await rd._approval_outcomes_note(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1")
            )

        assert "SEND_GMAIL" in note
        assert "the action did NOT run" in note

    async def test_an_undecided_approval_produces_no_note(self) -> None:
        """A still-pending gate has no outcome to report — saying anything about it is what the note exists to prevent."""
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = [_approval_card("a1", "pending")]
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ),
            patch.object(
                rd,
                "get_approval",
                new=AsyncMock(return_value=_record("a1", HILApprovalStatus.PENDING)),
            ),
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )

    async def test_a_lookup_failure_degrades_to_no_note(self) -> None:
        """The note is an enhancement; losing it must not take the delivery down."""
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new=AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert (
                await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))
                == ""
            )


class TestMergeResumedResultFailurePaths:
    """Every one of these is a write that silently matched nothing; reporting success here loses the user's result or cards."""

    async def _merge(
        self, *, existing, set_response=True, set_tool_data=True, new_cards=None, calls=None
    ):
        bot_message = MessageModel(type="bot", response="new text", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=set_response),
            ) as set_resp,
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=set_tool_data),
            ) as set_td,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            merged = await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"), bot_message, new_cards
            )
        if calls is not None:
            calls.update(get_message=get_msg, set_response=set_resp, set_tool_data=set_td)
        return merged

    async def test_a_missing_original_message_returns_none(self) -> None:
        assert await self._merge(existing=None) is None

    async def test_a_response_write_that_matched_nothing_returns_none(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        assert await self._merge(existing=existing, set_response=False) is None

    async def test_a_failed_card_write_keeps_the_cards_the_user_already_saw(self) -> None:
        """Falling back to the merged list reports unstored cards; falling back to nothing blanks the user's rendered turn."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(
            existing=existing,
            set_tool_data=False,
            new_cards=[{"tool_name": "new_tool", "data": {}}],
        )

        assert [e["tool_name"] for e in merged] == ["old_tool"]

    async def test_a_successful_merge_returns_original_plus_new_cards(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(
            existing=existing, new_cards=[{"tool_name": "new_tool", "data": {}}]
        )

        assert [e["tool_name"] for e in merged] == ["old_tool", "new_tool"]

    async def _merge_with_follow_ups(self, actions):
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        bot_message = MessageModel(type="bot", response="new text", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        bot_message.follow_up_actions = actions
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository, "set_message_follow_up_actions", new=AsyncMock()
            ) as set_fu,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"), bot_message, None
            )
        return set_fu

    async def test_follow_up_actions_are_written_onto_the_original_message(self) -> None:
        set_fu = await self._merge_with_follow_ups(["do the next thing"])

        set_fu.assert_awaited_once()
        assert set_fu.await_args.args == ("conv-1",)
        assert set_fu.await_args.kwargs["message_id"] == "orig-msg-1"
        assert set_fu.await_args.kwargs["user_id"] == "user-1"
        assert set_fu.await_args.kwargs["actions"] == ["do the next thing"]

    async def test_no_follow_ups_means_no_write(self) -> None:
        """An unconditional write would blank the follow-ups the original turn already had."""
        set_fu = await self._merge_with_follow_ups([])

        set_fu.assert_not_awaited()

    async def test_no_new_cards_skips_the_write_and_keeps_the_originals(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]

        merged = await self._merge(existing=existing, new_cards=None)

        assert [e["tool_name"] for e in merged] == ["old_tool"]

    async def test_every_write_is_scoped_to_this_conversation_message_and_user(self) -> None:
        """These are targeted in-place Mongo updates; an unscoped filter could edit somebody else's message."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = []
        calls: dict = {}

        await self._merge(
            existing=existing, new_cards=[{"tool_name": "new_tool", "data": {}}], calls=calls
        )

        read = calls["get_message"].await_args
        assert read.args == ("conv-1", "orig-msg-1")
        assert read.kwargs["user_id"] == "user-1"

        for name in ("set_response", "set_tool_data"):
            write = calls[name].await_args
            assert write.args == ("conv-1",), f"{name} was not scoped to the conversation"
            assert write.kwargs["message_id"] == "orig-msg-1", f"{name} targeted another message"
            assert write.kwargs["user_id"] == "user-1", f"{name} was not scoped to the owner"


class TestApprovalOutcomesNoteContent:
    """The note is the prompt the narrator is grounded on, so its content is a contract, not cosmetics.

    A dropped or mislabelled line is the agent telling the user an action
    is still pending after they denied it.
    """

    async def _note(self, cards, records):
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        message.tool_data = cards
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
            ) as get_msg,
            patch.object(rd, "get_approval", new=AsyncMock(side_effect=records.get)),
        ):
            note = await rd._approval_outcomes_note(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1")
            )
        return note, get_msg

    async def test_the_lookup_is_scoped_to_the_runs_own_message_and_owner(self) -> None:
        _note, get_msg = await self._note([], {})

        assert get_msg.await_args.args == ("conv-1", "orig-msg-1")
        assert get_msg.await_args.kwargs["user_id"] == "user-1"

    async def test_an_ordinary_card_does_not_stop_the_scan(self) -> None:
        """Cards arrive in stream order, so a plain tool card routinely sits before an approval; stopping there loses it."""
        cards = [{"tool_name": "web_search_tool", "data": {}}, _approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert "SEND_GMAIL" in note

    async def test_every_decided_approval_gets_its_own_line_in_card_order(self) -> None:
        cards = [_approval_card("a1", "pending"), _approval_card("a2", "pending")]
        records = {
            "a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL"),
            "a2": _record("a2", HILApprovalStatus.DENIED, tool_name="SEND_SLACK"),
        }

        note, _ = await self._note(cards, records)

        lines = [line for line in note.splitlines() if line.startswith("- ")]
        assert lines == [
            "- SEND_GMAIL: approved by the user; the action ran",
            "- SEND_SLACK: denied by the user; the action did NOT run",
        ]

    async def test_an_undecided_approval_is_dropped_from_a_mixed_batch(self) -> None:
        cards = [_approval_card("a1", "pending"), _approval_card("a2", "pending")]
        records = {
            "a1": _record("a1", HILApprovalStatus.PENDING, tool_name="SEND_GMAIL"),
            "a2": _record("a2", HILApprovalStatus.DENIED, tool_name="SEND_SLACK"),
        }

        note, _ = await self._note(cards, records)

        assert "SEND_GMAIL" not in note
        assert "SEND_SLACK" in note

    async def test_the_note_leads_with_the_override_instruction(self) -> None:
        """The header tells the narrator which text wins over the gate-time 'waiting for approval' text — contract, not decoration."""
        cards = [_approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert note.startswith("\n\n[APPROVAL OUTCOMES]")
        assert "overrides anything above" in note
        assert "never say it is pending and never re-offer approve/decline" in note

    async def test_the_whole_header_survives_verbatim(self) -> None:
        """Every clause declares the outcomes final, beats the gate-time text, and forbids re-offering — a reworded half hedges again."""
        cards = [_approval_card("a1", "pending")]
        records = {"a1": _record("a1", HILApprovalStatus.APPROVED, tool_name="SEND_GMAIL")}

        note, _ = await self._note(cards, records)

        assert note == (
            "\n\n[APPROVAL OUTCOMES] Final, decided by the user; this overrides anything above "
            "that says an action is waiting for approval. Report each action by its outcome; "
            "never say it is pending and never re-offer approve/decline.\n"
            "- SEND_GMAIL: approved by the user; the action ran"
        )


class TestMergeToolDataBookkeeping:
    """The upsert index has to keep pointing at the right slot as the list grows, or it overwrites an unrelated card."""

    def test_an_approval_first_seen_in_the_new_batch_indexes_its_own_slot(self) -> None:
        existing = [{"tool_name": "old_tool", "data": {"keep": "me"}}]

        merged = rd._merge_tool_data(
            existing, [_approval_card("a1", "pending"), _approval_card("a1", "approved")]
        )

        # The replay must land on the approval it appended, not on index 0.
        assert merged[0] == {"tool_name": "old_tool", "data": {"keep": "me"}}
        assert len(merged) == 2
        assert merged[1]["data"]["status"] == "approved"

    def test_skipping_a_pending_replay_does_not_abandon_the_rest_of_the_batch(self) -> None:
        """The replayed frame is rarely last — dropping out of the loop at it loses every card produced afterwards."""
        merged = rd._merge_tool_data(
            [_approval_card("a1", "approved")],
            [_approval_card("a1", "pending"), {"tool_name": "later_tool", "data": {}}],
        )

        assert [e.get("tool_name") for e in merged] == [
            APPROVAL_REQUEST_TOOL_NAME,
            "later_tool",
        ]
        assert merged[0]["data"]["status"] == "approved"


class TestReconcileLooksUpTheRightRecord:
    async def test_the_lookup_uses_the_cards_own_approval_id(self) -> None:
        """Reading a different approval's record stamps someone else's decision onto this card."""
        with patch.object(rd, "get_approval", new=AsyncMock(return_value=None)) as get_approval:
            await rd._reconcile_approval_statuses([_approval_card("a-42", "pending")])

        get_approval.assert_awaited_once_with("a-42")


class TestMergeResumedResultFailsClosed:
    async def test_a_run_without_a_user_id_scopes_to_empty_not_none(self) -> None:
        """user_id=None in a Mongo filter matches documents with no owner rather than nothing — scoping must fail closed."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        run = ExecutorRun(
            stream_id="queued_s1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id=""),
            kind=RunKind.QUEUED,
            task_id="task-1",
            user_message_id=None,
            bot_message_id="orig-msg-1",
        )
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ) as get_msg,
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd._merge_resumed_result(run, bot_message, None)

        assert get_msg.await_args.kwargs["user_id"] == ""


class TestDeliveredMessageIdentity:
    """Which id the delivered message carries decides whether the frontend reconciles onto its placeholder or strands it."""

    async def _deliver_run(self, run: ExecutorRun, follow_ups: list[str] | None = None):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd,
                "generate_follow_up_actions",
                new_callable=AsyncMock,
                return_value=follow_ups or [],
            ),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd, "_lookup_user_message_content", new_callable=AsyncMock, return_value="asked"
            ),
        ):
            await rd.deliver_result(run, "raw", "final", tool_data=None)
        return ws.await_args.args[1]["message"]

    async def test_a_queued_run_is_keyed_on_its_task_id(self) -> None:
        message = await self._deliver_run(_run(RunKind.QUEUED, task_id="task-7"))

        assert message["message_id"] == "task-7"
        assert message["task_id"] == "task-7"

    async def test_a_live_run_mints_a_fresh_id_and_advertises_no_task(self) -> None:
        """A live run never had a task_id-keyed placeholder, so emitting task_id would point the client's replace at nothing."""
        message = await self._deliver_run(_run(RunKind.LIVE, task_id="task-7"))

        # A real UUID, not just "not the task id": every live run falling back
        # to one shared constant would collide every message in the thread.
        UUID(message["message_id"])
        assert "task_id" not in message

    async def test_a_queued_run_quotes_the_message_it_answers(self) -> None:
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            kind=RunKind.QUEUED,
            task_id="task-7",
            user_message_id="user-msg-1",
        )

        message = await self._deliver_run(run)

        assert message["replyToMessage"]["id"] == "user-msg-1"

    async def test_a_hil_resume_never_quotes(self) -> None:
        """It merges onto the message under the user's turn, so a quote would have the turn quoting itself."""
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            kind=RunKind.QUEUED,
            task_id="task-7",
            user_message_id="user-msg-1",
            bot_message_id="orig-msg-1",
        )

        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(
                rd.conversation_repository,
                "get_message",
                new=AsyncMock(
                    return_value=MessageModel(type="bot", response="old", date="2026-01-01")
                ),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            await rd.deliver_result(run, "raw", "final", tool_data=None)

        assert "replyToMessage" not in ws.await_args.args[1]["message"]


class TestDeletedConversationDuringDelivery:
    async def _deliver_with_save_raising(self, exc: Exception):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock, side_effect=exc),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            result = await rd.deliver_result(_run(), "raw", "final", tool_data=None)
        return result, ws

    async def test_a_conversation_deleted_mid_run_ends_delivery_quietly(self) -> None:
        """The user deleted the conversation mid-run: there is nowhere to deliver to and nothing to push."""
        result, ws = await self._deliver_with_save_raising(HTTPException(status_code=404))

        assert result == (None, None)
        ws.assert_not_awaited()

    async def test_any_other_save_failure_also_stops_delivery(self) -> None:
        """Pushing a message that was never stored leaves the client showing a turn that vanishes on reload."""
        result, ws = await self._deliver_with_save_raising(HTTPException(status_code=500))

        assert result == (None, None)
        ws.assert_not_awaited()


class TestMergedCardsAreActuallyWritten:
    async def test_the_merged_list_is_what_reaches_mongo(self) -> None:
        """Returning the merged cards while storing something else means the live push shows them but the reload does not."""
        existing = MessageModel(type="bot", response="old", date="2026-01-01")
        existing.tool_data = [{"tool_name": "old_tool", "data": {}}]
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=True),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=True),
            ) as set_td,
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
        ):
            merged = await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"),
                bot_message,
                [{"tool_name": "new_tool", "data": {}}],
            )

        assert set_td.await_args.kwargs["entries"] == merged
        assert [e["tool_name"] for e in set_td.await_args.kwargs["entries"]] == [
            "old_tool",
            "new_tool",
        ]

    async def test_the_outcomes_lookup_also_fails_closed_without_a_user_id(self) -> None:
        message = MessageModel(type="bot", response="x", date="2026-01-01")
        run = ExecutorRun(
            stream_id="",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id=""),
            kind=RunKind.QUEUED,
            task_id="task-1",
            user_message_id=None,
            bot_message_id="orig-msg-1",
        )
        with patch.object(
            rd.conversation_repository, "get_message", new=AsyncMock(return_value=message)
        ) as get_msg:
            await rd._approval_outcomes_note(run)

        assert get_msg.await_args.kwargs["user_id"] == ""


class TestDeferredFollowUpPush:
    """Follow-ups are generated AFTER the answer ships, so the spinner clears first and they arrive as a second push."""

    async def _push(self, *, generated, persisted=True):
        bot_message = MessageModel(type="bot", response="answered", date="2026-01-01")
        bot_message.message_id = "msg-1"
        with (
            patch.object(rd, "_build_follow_up_actions", new=AsyncMock(return_value=generated)),
            patch.object(rd, "_persist_follow_up_actions", new=AsyncMock(return_value=persisted)),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
        ):
            run = _run(RunKind.QUEUED, task_id="task-7")
            await rd._generate_and_push_follow_ups(
                bot_message=bot_message,
                result_type="final",
                tool_data=None,
                target=rd._DeliveryTarget(
                    user_id=run.user.user_id,
                    conversation_id=run.conversation_id,
                    task_id=run.task_id,
                    emit_task_id=run.is_queued,
                    show_reply_quote=False,
                    user_message_id=run.user_message_id,
                    user_msg_content="asked",
                ),
            )
        return ws

    async def test_suggestions_reach_the_client_on_the_same_message(self) -> None:
        ws = await self._push(generated=["ask about X", "try Y"])

        event = ws.await_args.args[1]
        assert event["message"]["message_id"] == "msg-1"
        assert event["message"]["follow_up_actions"] == ["ask about X", "try Y"]

    async def test_nothing_generated_means_no_second_push(self) -> None:
        ws = await self._push(generated=[])

        ws.assert_not_awaited()

    async def test_suggestions_that_failed_to_persist_are_never_shown(self) -> None:
        """Broadcasting unstored suggestions puts them on screen only for them to vanish on reload."""
        ws = await self._push(generated=["ask about X"], persisted=False)

        ws.assert_not_awaited()


def _logged(mock, level: str) -> tuple[str, dict]:
    """(message, kwargs) of the last call at level, message asserted real.

    warning/error/critical/exception put BOTH halves on the wide event —
    wide_events._append stores {"msg": message, **kwargs} — so a blanked or
    dropped message is a real regression in errors[]/warnings[], not prose. The
    wording is deliberately not pinned; that it exists at all is.
    """
    call = getattr(mock, level).call_args
    assert call is not None, f"nothing was logged at {level}"
    assert call.args and isinstance(call.args[0], str) and call.args[0].strip(), (
        f"{level} was emitted with no message — errors[] would carry msg=None"
    )
    return call.args[0], call.kwargs


class TestFailurePathsAreDiagnosable:
    """Every branch here drops a user's result on the floor.

    The structured log fields are the only way to find which conversation
    and message it happened to — a blanked id turns an incident into a
    search of the whole collection. Asserting them is a structural assert
    (tests/CLAUDE.md rule 7); the prose message is deliberately not asserted.
    """

    async def _merge_with_log(self, *, existing, set_response=True, set_tool_data=True):
        bot_message = MessageModel(type="bot", response="new", date="2026-01-01")
        bot_message.message_id = "orig-msg-1"
        with (
            patch.object(
                rd.conversation_repository, "get_message", new=AsyncMock(return_value=existing)
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_response",
                new=AsyncMock(return_value=set_response),
            ),
            patch.object(
                rd.conversation_repository,
                "set_message_tool_data",
                new=AsyncMock(return_value=set_tool_data),
            ),
            patch.object(rd, "get_approval", new=AsyncMock(return_value=None)),
            patch.object(rd, "log") as log,
        ):
            await rd._merge_resumed_result(
                _run(RunKind.QUEUED, bot_message_id="orig-msg-1"),
                bot_message,
                [{"tool_name": "new_tool", "data": {}}],
            )
        return log

    async def test_a_missing_original_message_names_what_was_looked_for(self) -> None:
        log = await self._merge_with_log(existing=None)

        _msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}

    async def test_a_response_write_that_matched_nothing_names_the_message(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        log = await self._merge_with_log(existing=existing, set_response=False)

        _msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}

    async def test_a_dropped_card_write_names_the_message(self) -> None:
        existing = MessageModel(type="bot", response="old", date="2026-01-01")

        log = await self._merge_with_log(existing=existing, set_tool_data=False)

        msg, kwargs = _logged(log, "error")
        assert kwargs == {"conversation_id": "conv-1", "message_id": "orig-msg-1"}
        # The two adjacent literals must still join into one sentence.
        assert msg.endswith("dropping cards")

    async def test_a_failed_outcomes_lookup_reports_the_cause(self) -> None:
        with (
            patch.object(
                rd.conversation_repository,
                "get_message",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch.object(rd, "log") as log,
        ):
            await rd._approval_outcomes_note(_run(RunKind.QUEUED, bot_message_id="orig-msg-1"))

        _msg, kwargs = _logged(log, "warning")
        assert kwargs == {"error": "mongo down"}


class TestDeletedConversationIsNotAnError:
    """#906 split these arms on purpose: a deleted-mid-run conversation is expected, not an error-level event.

    Both arms return the same thing, so the LEVEL is the entire observable
    difference — without this test the split could be quietly undone.
    """

    async def _deliver_with_save_raising(self, exc: Exception):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock, side_effect=exc),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
            patch.object(rd, "log") as log,
        ):
            result = await rd.deliver_result(_run(), "raw", "final", tool_data=None)
        return result, log

    async def test_a_deleted_conversation_is_reported_at_info_with_its_id(self) -> None:
        result, log = await self._deliver_with_save_raising(HTTPException(status_code=404))

        assert result == (None, None)
        assert log.info.call_args.kwargs == {"conversation_id": "conv-1"}
        assert not log.error.called, "an expected 404 was escalated into errors[]"

    async def test_any_other_http_failure_is_reported_at_error_with_the_cause(self) -> None:
        result, log = await self._deliver_with_save_raising(
            HTTPException(status_code=500, detail="mongo exploded")
        )

        assert result == (None, None)
        _msg, kwargs = _logged(log, "error")
        assert kwargs["error"] == "500: mongo exploded"
        assert not log.info.called, "a real failure was downgraded to info"

    async def test_a_non_http_failure_also_carries_its_cause(self) -> None:
        """The second except arm: a save that dies on a driver error (never an HTTPException) needs its own cause reported too."""
        result, log = await self._deliver_with_save_raising(RuntimeError("connection reset"))

        assert result == (None, None)
        _msg, kwargs = _logged(log, "error")
        assert kwargs["error"] == "connection reset"
        assert not log.info.called


class TestBuildFollowUpActions:
    """The executor-final follow-up one-shot: what it is asked, and under which routing key.

    Every caller mocks generate_follow_up_actions, so nothing else asserts
    the arguments it is handed.
    """

    async def _build(
        self,
        *,
        msg_type: str = "final",
        notification_text: str = "Archived 3 emails.",
        user_msg_content: str = "clean my inbox",
        user_id: str = "user-1",
        conversation_id: str | None = "conv-1",
    ) -> AsyncMock:
        with patch.object(
            rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=["a"]
        ) as gen:
            self.result = await rd._build_follow_up_actions(
                msg_type=msg_type,
                notification_text=notification_text,
                user_msg_content=user_msg_content,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        return gen

    async def test_the_sticky_routing_key_is_the_conversation(self) -> None:
        """session_id chains these with the graph-path follow-ups; without it every call lands on a random upstream, missing cache."""
        gen = await self._build()

        assert gen.call_args.args[2] == {
            "configurable": {"user_id": "user-1", "session_id": "conv-1"}
        }

    async def test_a_conversationless_run_still_names_its_user(self) -> None:
        gen = await self._build(conversation_id=None)

        assert gen.call_args.args[2] == {"configurable": {"user_id": "user-1", "session_id": None}}

    async def test_the_prompt_pairs_the_request_with_the_answer(self) -> None:
        gen = await self._build()

        assert gen.call_args.args[0] == (
            "User request: clean my inbox\n\nAssistant response: Archived 3 emails."
        )

    async def test_without_a_user_message_the_answer_stands_alone(self) -> None:
        gen = await self._build(user_msg_content="")

        assert gen.call_args.args[0] == "Archived 3 emails."

    async def test_the_spend_is_attributed_to_the_run_owner(self) -> None:
        gen = await self._build()

        assert gen.call_args.args[1] == "user-1"

    async def test_a_non_final_result_asks_for_nothing(self) -> None:
        """An error or intermediate ack gets no suggestions, and costs no call."""
        gen = await self._build(msg_type="error")

        assert self.result == []
        gen.assert_not_awaited()


def _quoting_run(user: dict | None = None) -> ExecutorRun:
    """Build a queued run that answers a specific user message, so it quotes it."""
    return ExecutorRun(
        stream_id="",
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id="user-1") if user is None else user,
        kind=RunKind.QUEUED,
        task_id="task-7",
        user_message_id="user-msg-1",
    )


def _target(**over) -> rd._DeliveryTarget:
    """Build the delivery target a quoting queued run produces."""
    fields: dict = {
        "user_id": "user-1",
        "conversation_id": "conv-1",
        "task_id": "task-7",
        "emit_task_id": True,
        "show_reply_quote": True,
        "user_message_id": "user-msg-1",
        "user_msg_content": "what I asked",
    }
    return rd._DeliveryTarget(**{**fields, **over})


class TestNarrateResultCallContract:
    """Exactly what comms is handed to re-voice a result.

    Every one of these is a scoping key: the conversation decides which
    checkpoint (and therefore which persona and history) comms loads, the user
    decides whose it is, and the workflow_id switches it to the workflow voice.
    A blanked or dropped one still returns text, so nothing downstream notices
    that the text was voiced for the wrong conversation.
    """

    async def test_every_argument_comms_needs_arrives_intact(self) -> None:
        calls: list[tuple[tuple, dict]] = []

        async def _record(
            result_text: str,
            msg_type: str,
            conversation_id: str,
            user,
            returned_note: str = "",
            workflow_id: str | None = None,
        ) -> str:
            calls.append(
                (
                    (result_text, msg_type, conversation_id, user),
                    {"returned_note": returned_note, "workflow_id": workflow_id},
                )
            )
            return "voiced"

        with patch.object(rd, "narrate_executor_result", new=_record):
            narrated = await rd._narrate_result(
                _run(workflow=True), "raw text", "final", "handed back by the subagent"
            )

        assert narrated == "voiced"
        assert calls == [
            (
                ("raw text", "final", "conv-1", AuthenticatedUser(user_id="user-1")),
                {"returned_note": "handed back by the subagent", "workflow_id": "wf-1"},
            )
        ]

    async def test_the_decided_approval_outcomes_ride_on_the_result_text(self) -> None:
        """The note stops comms re-offering an approve/decline the user already answered, so it must be in the text comms reads."""
        with (
            patch.object(
                rd, "_approval_outcomes_note", new=AsyncMock(return_value="\n\n[APPROVAL] done")
            ),
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ) as narrate,
        ):
            await rd._narrate_result(_run(), "raw text", "final", "")

        assert narrate.await_args.args[0] == "raw text\n\n[APPROVAL] done"


class TestBuildBotMessageShape:
    """The saved-and-delivered bubble: the client renders on type and orders the thread on date, both load-bearing."""

    def test_it_is_a_bot_bubble_carrying_the_voiced_text(self) -> None:
        message = rd._build_bot_message(_run(), "voiced", None, is_hil_resume=False)

        assert message.type == "bot"
        assert message.response == "voiced"

    def test_the_timestamp_is_a_real_utc_instant(self) -> None:
        """A naive local stamp sorts the message wrong in a UTC thread; a missing one drops it out of the ordering entirely."""
        before = datetime.now(UTC)
        message = rd._build_bot_message(_run(), "voiced", None, is_hil_resume=False)
        after = datetime.now(UTC)

        assert message.date.endswith("+00:00"), "must be an explicit UTC offset, not local time"
        assert before <= datetime.fromisoformat(message.date) <= after


class TestAttachReplyQuoteLookup:
    """The quote the user sees above a queued answer.

    It is read back from Mongo by (conversation, message, owner); any one of
    those three being wrong either reads a stranger's message or reads nothing
    and silently quotes an empty bubble.
    """

    async def _attach(self, run: ExecutorRun, *, is_hil_resume: bool = False):
        bot_message = MessageModel(type="bot", response="voiced", date="2026-01-01")
        with patch.object(
            rd.conversation_repository,
            "get_message",
            new_callable=AsyncMock,
            return_value=MessageModel(type="user", response="what I asked", date="2026-01-01"),
        ) as get:
            result = await rd._attach_reply_quote(run, bot_message, is_hil_resume=is_hil_resume)
        return result, get, bot_message

    async def test_the_lookup_is_scoped_to_this_conversation_message_and_owner(self) -> None:
        result, get, _bot_message = await self._attach(_quoting_run())

        assert get.await_args.args == ("conv-1", "user-msg-1")
        assert get.await_args.kwargs == {"user_id": "user-1"}
        assert result == (True, "what I asked")

    async def test_a_run_with_no_user_id_scopes_to_empty_not_none(self) -> None:
        """user_id=None is an unscoped read in the repository layer; the empty string matches nothing, the safe miss."""
        _result, get, _bot_message = await self._attach(
            _quoting_run(user=AuthenticatedUser(user_id=""))
        )

        assert get.await_args.kwargs == {"user_id": ""}

    async def test_the_bubble_quotes_the_user_message_verbatim(self) -> None:
        _result, _get, bot_message = await self._attach(_quoting_run())

        assert bot_message.replyToMessage == ReplyToMessageData(
            id="user-msg-1", content="what I asked", role="user"
        )

    async def test_a_live_run_neither_quotes_nor_reads(self) -> None:
        """Live answers land directly under the user's turn, so a quote is noise and the lookup a pointless round trip."""
        result, get, bot_message = await self._attach(_run())

        assert result == (False, "")
        get.assert_not_awaited()
        assert bot_message.replyToMessage is None

    async def test_a_hil_resume_neither_quotes_nor_reads(self) -> None:
        result, get, bot_message = await self._attach(_quoting_run(), is_hil_resume=True)

        assert result == (False, "")
        get.assert_not_awaited()
        assert bot_message.replyToMessage is None


class TestBroadcastPayloadIsWhatTheClientUpserts:
    """The WebSocket message body, whole: the client upserts on these exact keys, so a renamed one silently never shows."""

    async def _broadcast(self, target: rd._DeliveryTarget):
        bot_message = MessageModel(type="bot", response="voiced", date="2026-01-01T00:00:00+00:00")
        bot_message.message_id = "msg-1"
        with patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws:
            await rd._broadcast_bot_message(
                target=target,
                bot_message=bot_message,
                notification_text="voiced",
                tool_data=None,
                follow_up_actions=[],
            )
        return ws

    async def test_a_quoting_push_carries_the_whole_reply_quote(self) -> None:
        ws = await self._broadcast(_target())

        assert ws.await_args.args[1]["message"] == {
            "type": "bot",
            "response": "voiced",
            "message_id": "msg-1",
            "date": "2026-01-01T00:00:00+00:00",
            "kind": "text",
            "task_id": "task-7",
            "replyToMessage": {
                "id": "user-msg-1",
                "content": "what I asked",
                "role": "user",
            },
        }

    async def test_a_non_quoting_push_omits_the_quote_entirely(self) -> None:
        ws = await self._broadcast(_target(show_reply_quote=False, emit_task_id=False))

        assert ws.await_args.args[1]["message"] == {
            "type": "bot",
            "response": "voiced",
            "message_id": "msg-1",
            "date": "2026-01-01T00:00:00+00:00",
            "kind": "text",
        }


class TestSpawnDeferredFollowUps:
    """The detached follow-up task is handed the delivery context by value.

    If any of it goes missing the task dies on its own boundary and the
    suggestions never arrive, with the answer already shipped.
    """

    async def test_the_detached_task_gets_the_whole_delivery_context(self) -> None:
        captured: dict = {}

        async def _record(**kwargs) -> None:
            captured.update(kwargs)

        spawned: list = []
        bot_message = MessageModel(type="bot", response="voiced", date="2026-01-01")

        with (
            patch.object(rd, "_generate_and_push_follow_ups", new=_record),
            patch.object(rd, "spawn_background_task", side_effect=spawned.append),
        ):
            rd._spawn_deferred_follow_ups(
                bot_message=bot_message,
                result_type="final",
                tool_data=CARDS,
                target=_target(),
            )

        assert len(spawned) == 1
        await spawned[0]
        assert captured == {
            "bot_message": bot_message,
            "result_type": "final",
            "tool_data": CARDS,
            "target": _target(),
        }


class TestDeliveryContextIsThreadedWhole:
    """_narrate_and_deliver is the one place the run is unpacked into the values every downstream helper works from.

    A field lost here is lost for the rest of delivery, and every one of
    them reads as a working send.
    """

    async def _deliver_queued(self, **patches):
        """deliver_result over the WebSocket path for a quoting queued run."""
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd,
                "_lookup_user_message_content",
                new_callable=AsyncMock,
                return_value="what I asked",
            ),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "_spawn_deferred_follow_ups") as spawn,
        ):
            await rd.deliver_result(_quoting_run(), "raw", "final", tool_data=None)
        return ws, spawn

    async def test_the_push_is_addressed_to_the_runs_owner(self) -> None:
        """The broadcast is a per-user fan-out: a blank owner reaches nobody while every log line still reads delivered."""
        ws, _spawn = await self._deliver_queued()

        assert ws.await_args.args[0] == "user-1"

    async def test_the_quote_the_user_sees_survives_the_hand_off(self) -> None:
        ws, _spawn = await self._deliver_queued()

        assert ws.await_args.args[1]["message"]["replyToMessage"] == {
            "id": "user-msg-1",
            "content": "what I asked",
            "role": "user",
        }

    async def test_the_deferred_follow_ups_get_the_same_target(self) -> None:
        _ws, spawn = await self._deliver_queued()

        assert spawn.call_args.kwargs["target"] == _target()

    async def test_the_returned_note_reaches_comms(self) -> None:
        """The subagent's hand-back note is context comms cannot re-derive; if dropped, the answer just comes back thinner."""
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ) as narrate,
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
        ):
            await rd.deliver_result(
                _run(), "raw", "final", "handed back by the subagent", tool_data=None
            )

        assert narrate.await_args.kwargs["returned_note"] == "handed back by the subagent"


class TestWorkflowNotificationRef:
    """The workflow identity handed to the notification dispatcher.

    It decides what the user is told finished and whether they are told
    at all, and the run it was read off is gone by then.
    """

    async def _deliver_workflow(self, *, notify_on_completion: bool):
        run = replace(_run(workflow=True), workflow_notify_on_completion=notify_on_completion)
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock),
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock) as notify,
        ):
            await rd.deliver_result(run, result_text="done", result_type="final", tool_data=None)
        return notify

    async def test_a_notifying_workflow_is_named_in_full(self) -> None:
        notify = await self._deliver_workflow(notify_on_completion=True)

        assert notify.await_args.kwargs["workflow"] == rd._WorkflowRef(
            workflow_id="wf-1", workflow_title="Morning digest", notify_on_completion=True
        )

    async def test_a_silent_workflow_stays_silent_through_the_hand_off(self) -> None:
        """notify_on_completion defaults to True on _WorkflowRef, so a lost flag here starts notifying against the user's setting."""
        notify = await self._deliver_workflow(notify_on_completion=False)

        assert notify.await_args.kwargs["workflow"] == rd._WorkflowRef(
            workflow_id="wf-1", workflow_title="Morning digest", notify_on_completion=False
        )


class TestRunBoundaryCarriesTheOriginatingSurface:
    """The executor run stamps the turn's surface on its own wide event.

    An auxiliary call made INSIDE this run (a follow-up, a memory write) is
    handed a bare config with no conversation_source, so without this stamp
    the ledger records a user's web turn as system — and executor turns are
    the expensive ones, so the under-count lands exactly where COGS-by-channel
    is read.
    """

    @staticmethod
    async def _boundary_fields(configurable: dict[str, object]) -> dict[str, object]:
        from app.agents.core.background.executor_runner import _ExecutorResult

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
        )
        with (
            patch("app.agents.core.background.executor_runner.capture_event"),
            patch.object(
                er,
                "_execute_executor",
                new_callable=AsyncMock,
                return_value=_ExecutorResult("done", "final"),
            ),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
            patch.object(er, "wide_task") as boundary,
        ):
            await er.run_executor_background(run, "do things", configurable)
        return boundary.call_args.kwargs

    async def test_the_turns_surface_is_carried_onto_the_run(self) -> None:
        fields = await self._boundary_fields({"user_id": "u1", "conversation_source": "web"})

        assert fields["conversation_source"] == "web"

    async def test_a_run_started_from_no_surface_carries_none(self) -> None:
        """A workflow-triggered executor run has no originating surface; None is the honest value, the ledger classifies it."""
        fields = await self._boundary_fields({"user_id": "u1"})

        assert fields["conversation_source"] is None


@pytest.mark.regression
class TestRunBoundaryCarriesWorkflowExecution:
    """run_executor_background opens its own wide-event boundary; the workflow task stamped execution_id on ITS boundary.

    Unless the run carries it across, model calls land in the ledger with
    a workflow but no execution — $8 of a $10 workflow day was attributed
    to no run at all.
    """

    async def test_executor_calls_see_the_workflow_execution(self) -> None:
        from app.agents.core.background.executor_runner import _ExecutorResult
        from shared.py.wide_events import log

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
            workflow_id="wf-9",
            workflow_execution_id="exec-42",
        )
        seen: dict[str, object] = {}

        async def capture(*_args: object, **_kwargs: object) -> _ExecutorResult:
            seen["workflow"] = log.get().get("workflow")
            return _ExecutorResult("done", "final")

        with (
            patch("app.agents.core.background.executor_runner.capture_event"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(
                run, "do things", {"user_id": "user-1", "workflow_id": "wf-9"}
            )

        assert seen["workflow"] == {"id": "wf-9", "execution_id": "exec-42"}

    @pytest.mark.parametrize(
        ("workflow_id", "execution_id"),
        [("wf-9", None), (None, "exec-42"), (None, None)],
        ids=["workflow-without-execution", "execution-without-workflow", "plain-run"],
    )
    async def test_a_run_missing_either_id_stamps_no_workflow(
        self, workflow_id: str | None, execution_id: str | None
    ) -> None:
        """Half an identity is worse than none: a workflow id alone attributes calls to the workflow's *unknown* execution."""
        from app.agents.core.background.executor_runner import _ExecutorResult
        from shared.py.wide_events import log

        run = ExecutorRun(
            stream_id="stream-1",
            conversation_id="conv-1",
            user=AuthenticatedUser(user_id="user-1"),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
            workflow_id=workflow_id,
            workflow_execution_id=execution_id,
        )
        seen: dict[str, object] = {}

        async def capture(*_args: object, **_kwargs: object) -> _ExecutorResult:
            seen["workflow"] = log.get().get("workflow")
            return _ExecutorResult("done", "final")

        with (
            patch("app.agents.core.background.executor_runner.capture_event"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": "user-1"})

        assert seen["workflow"] is None


class TestCommsDirectiveDelivery:
    """Comms can answer a not-mention-worthy background update with a control line: SILENCE (deliver nothing) or REACT (a one-emoji acknowledgment)."""

    async def test_silence_delivers_nothing_on_any_surface(self) -> None:
        with patch.object(rd, "capture_event") as capture:
            save, platform, ws = await _deliver(
                ConversationSource.WHATSAPP, comms_text="SILENCE: routine calendar refresh"
            )
        save.assert_not_awaited()
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        # Attributed to the run's owner, or the funnel joins nobody. One resolution
        # event per update, tagged with the outcome; the reason text never leaves.
        capture.assert_called_once()
        assert capture.call_args.args[0] == "user-1"
        assert capture.call_args.args[1] == rd.AnalyticsEvents.CHAT_BACKGROUND_UPDATE_RESOLVED
        assert capture.call_args.args[2] == {"outcome": "silence"}

    async def test_silence_on_web_broadcasts_nothing(self) -> None:
        save, platform, ws = await _deliver(
            ConversationSource.WEB, comms_text="SILENCE: nothing new"
        )
        save.assert_not_awaited()
        ws.assert_not_awaited()
        platform.assert_not_awaited()

    async def test_react_delivers_the_emoji_as_the_message_on_a_bot(self) -> None:
        with patch.object(rd, "capture_event") as capture:
            save, platform, _ws = await _deliver(
                ConversationSource.WHATSAPP, comms_text="REACT: 👍"
            )
        platform.assert_awaited_once()
        assert platform.await_args.args[2] == "👍"
        capture.assert_called_once()
        assert capture.call_args.args[0] == "user-1"
        assert capture.call_args.args[1] == rd.AnalyticsEvents.CHAT_BACKGROUND_UPDATE_RESOLVED
        assert capture.call_args.args[2] == {
            "outcome": "react",
            "emoji": "👍",
            "delivery": "fallback_text",
        }
        # The ack intent is recorded on the persisted message, not left to be
        # reverse-engineered from the body being emoji-only.
        assert save.await_args.args[0].messages[0].kind is rd.MessageKind.EMOJI_ACK

    async def test_react_delivers_the_emoji_over_websocket_on_web(self) -> None:
        save, _platform, ws = await _deliver(ConversationSource.WEB, comms_text="REACT: ✅")
        ws.assert_awaited_once()
        assert ws.await_args.args[1]["message"]["response"] == "✅"
        assert save.await_args.args[0].messages[0].kind is rd.MessageKind.EMOJI_ACK

    async def test_react_attaches_a_native_reaction_when_the_platform_id_is_known(
        self,
    ) -> None:
        """The recorded platform id turns the ack into a real reaction: the reaction envelope goes out and no text bubble is sent."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="REACT: 👍"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd,
                "_lookup_platform_message_id",
                new_callable=AsyncMock,
                return_value="wamid.123",
            ),
            patch.object(
                rd, "deliver_reaction_to_platform", new_callable=AsyncMock, return_value=True
            ) as react,
            patch.object(rd, "deliver_message_to_platform", new_callable=AsyncMock) as platform,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "capture_event") as capture,
        ):
            await rd.deliver_result(run, result_text="raw", result_type="final", tool_data=None)
        react.assert_awaited_once_with(
            ConversationSource.WHATSAPP,
            "user-1",
            "wamid.123",
            "👍",
            conversation_id="conv-1",
        )
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        # The ack is still persisted (history/audit), targeted at the GAIA
        # message it answers so every surface can render it as a reaction.
        saved = save.await_args.args[0].messages[0]
        assert saved.kind is rd.MessageKind.EMOJI_ACK
        assert saved.response == "👍"
        assert saved.reacts_to_message_id == "user-msg-1"
        assert capture.call_args.args[2] == {
            "outcome": "react",
            "emoji": "👍",
            "delivery": "reaction",
        }

    async def test_react_falls_back_to_text_without_a_platform_id(self) -> None:
        """Older turns and non-bot triggers have no recorded platform id: the emoji goes out as a text bubble and the ack is never lost."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="REACT: 👍"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(
                rd,
                "_get_conversation_source",
                new_callable=AsyncMock,
                return_value=ConversationSource.WHATSAPP,
            ),
            patch.object(
                rd, "_lookup_platform_message_id", new_callable=AsyncMock, return_value=None
            ),
            patch.object(rd, "deliver_reaction_to_platform", new_callable=AsyncMock) as react,
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ) as platform,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
        ):
            await rd.deliver_result(run, result_text="raw", result_type="final", tool_data=None)
        react.assert_not_awaited()
        platform.assert_awaited_once()
        assert platform.await_args.args[2] == "👍"

    async def test_web_badge_payload_carries_kind_and_reaction_target(self) -> None:
        """The web client renders an emoji-ack as a badge on the answered message, not a new bubble — it needs kind + target in the push."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="REACT: ✅"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd,
                "_lookup_user_message_content",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "_spawn_deferred_follow_ups"),
        ):
            await rd.deliver_result(run, result_text="raw", result_type="final", tool_data=None)
        message = ws.await_args.args[1]["message"]
        assert message["response"] == "✅"
        assert message["kind"] == "emoji_ack"
        assert message["reacts_to_message_id"] == "user-msg-1"

    async def test_react_resolves_to_no_speakable_text(self) -> None:
        """Voice must not read the emoji aloud: a react returns (None, id)."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="REACT: ✅"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd,
                "_lookup_user_message_content",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
            patch.object(rd, "_spawn_deferred_follow_ups"),
        ):
            text, message_id = await rd.deliver_result(
                run, result_text="raw", result_type="final", tool_data=None
            )
        assert text is None
        assert message_id

    async def test_react_spawns_no_deferred_follow_ups(self) -> None:
        """Follow-up chips attach to a rendered message; a badge has none, so generating them burns an LLM call for chips that go nowhere."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="REACT: ✅"
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                rd,
                "_lookup_user_message_content",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock),
            patch.object(rd, "_spawn_deferred_follow_ups") as spawn,
        ):
            await rd.deliver_result(run, result_text="raw", result_type="final", tool_data=None)
        spawn.assert_not_called()

    async def test_ordinary_text_still_delivers_normally(self) -> None:
        with patch.object(rd, "capture_event") as capture:
            save, platform, _ws = await _deliver(
                ConversationSource.WHATSAPP, comms_text="Booked your 9am flight."
            )
        assert platform.await_args.args[2] == "Booked your 9am flight."
        # The baseline outcome is captured too, so silence/react rates have a
        # denominator; an ordinary message stays MessageKind.TEXT.
        assert capture.call_args.args[1] == rd.AnalyticsEvents.CHAT_BACKGROUND_UPDATE_RESOLVED
        assert capture.call_args.args[2] == {"outcome": "reply", "delivery": "message"}
        assert save.await_args.args[0].messages[0].kind is rd.MessageKind.TEXT


@dataclass
class _Delivered:
    """Every seam one deliver_result call touched, plus the wide event it wrote."""

    returned: tuple[str | None, str | None]
    event: dict[str, Any]
    save: AsyncMock
    platform: AsyncMock
    reaction: AsyncMock
    lookup: AsyncMock
    ws: AsyncMock
    follow_ups: AsyncMock
    spawn: MagicMock
    capture: MagicMock
    to_platforms: AsyncMock
    notify: AsyncMock


@dataclass(frozen=True)
class _Seams:
    """What the stubbed I/O seams answer during one delivery."""

    comms_text: str
    source: ConversationSource | None
    follow_ups: list[str] | None = None
    platform_id: str | None = None


async def _deliver_run(
    run: ExecutorRun,
    seams: _Seams,
    *,
    result_type: str = "final",
    tool_data: list[ToolDataEntry] | None = None,
) -> _Delivered:
    """Run deliver_result with every I/O seam recorded; the routing logic runs for real."""
    async with captured_wide_event() as event:
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value=seams.comms_text
            ),
            patch.object(
                rd,
                "generate_follow_up_actions",
                new_callable=AsyncMock,
                return_value=seams.follow_ups or [],
            ) as generated,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(
                rd, "_get_conversation_source", new_callable=AsyncMock, return_value=seams.source
            ),
            patch.object(
                rd, "_lookup_user_message_content", new_callable=AsyncMock, return_value=""
            ),
            patch.object(
                rd,
                "_lookup_platform_message_id",
                new_callable=AsyncMock,
                return_value=seams.platform_id,
            ) as lookup,
            patch.object(
                rd, "deliver_reaction_to_platform", new_callable=AsyncMock, return_value=True
            ) as reaction,
            patch.object(
                rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
            ) as platform,
            patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
            patch.object(rd, "_spawn_deferred_follow_ups") as spawn,
            patch.object(rd, "capture_event") as capture,
            patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock) as to_platforms,
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock) as notify,
        ):
            returned = await rd.deliver_result(
                run, result_text="raw", result_type=result_type, tool_data=tool_data
            )
    return _Delivered(
        returned=returned,
        event=event,
        save=save,
        platform=platform,
        reaction=reaction,
        lookup=lookup,
        ws=ws,
        follow_ups=generated,
        spawn=spawn,
        capture=capture,
        to_platforms=to_platforms,
        notify=notify,
    )


def _saved(delivered: _Delivered) -> MessageModel:
    return delivered.save.await_args.args[0].messages[0]


class TestTheCommsVerdictIsOnTheWideEvent:
    @pytest.mark.parametrize(
        ("comms_text", "expected"),
        [
            (
                "SILENCE: routine refresh",
                {"comms_delivery": "silenced", "silence_reason": "routine refresh"},
            ),
            ("REACT: 👍", {"comms_delivery": "reacted"}),
            ("Booked your flight.", {"comms_delivery": "message"}),
        ],
    )
    async def test_how_comms_answered_is_recorded(
        self, comms_text: str, expected: dict[str, str]
    ) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text=comms_text, source=ConversationSource.WHATSAPP)
        )

        assert {key: delivered.event.get(key) for key in expected} == expected
        assert ("silence_reason" in delivered.event) is ("silence_reason" in expected)


class TestResolutionAnalyticsIsOnePerUpdate:
    """One chat:background_update_resolved per update, deduped on the task (or conversation) it resolved."""

    async def test_a_queued_run_dedupes_on_its_task(self) -> None:
        delivered = await _deliver_run(
            _run(RunKind.QUEUED, task_id="task-7"), _Seams(comms_text="Done.", source=None)
        )

        assert delivered.capture.call_args.kwargs == {
            "dedupe_key": "chat_background_update_resolved:task-7"
        }

    async def test_a_taskless_run_dedupes_on_its_conversation(self) -> None:
        delivered = await _deliver_run(_run(), _Seams(comms_text="Done.", source=None))

        assert delivered.capture.call_args.kwargs == {
            "dedupe_key": "chat_background_update_resolved:conv-1"
        }

    async def test_a_web_react_lands_as_a_badge(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(comms_text="REACT: ✅", source=None),
        )

        assert delivered.capture.call_args.args[2] == {
            "outcome": "react",
            "emoji": "✅",
            "delivery": "badge",
        }

    async def test_a_web_reply_is_delivered_over_the_websocket(self) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text="Done.", source=ConversationSource.WEB)
        )

        assert delivered.event["result_delivery"]["transport"] == "websocket"
        assert delivered.event["result_delivery"]["delivered"] is True


class TestInlineFollowUpsOnlyWhereNothingWaits:
    """Only a workflow attaches follow-ups inline; web and bot paths defer them; a reaction gets none."""

    async def test_a_bot_reaction_generates_no_follow_ups(self) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text="REACT: 👍", source=ConversationSource.WHATSAPP)
        )

        delivered.follow_ups.assert_not_awaited()

    async def test_the_web_answer_is_not_gated_on_follow_ups(self) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text="Done.", source=ConversationSource.WEB), tool_data=CARDS
        )

        delivered.follow_ups.assert_not_awaited()
        kwargs = delivered.spawn.call_args.kwargs
        assert kwargs["bot_message"].message_id == _saved(delivered).message_id
        assert kwargs["result_type"] == "final"
        assert kwargs["tool_data"] == CARDS
        assert kwargs["target"].conversation_id == "conv-1"

    async def test_a_web_ack_with_no_answered_message_carries_no_reaction_target(self) -> None:
        delivered = await _deliver_run(_run(), _Seams(comms_text="REACT: ✅", source=None))

        assert "reacts_to_message_id" not in delivered.ws.await_args.args[1]["message"]


class TestAWorkflowResult:
    async def test_a_finished_workflow_reaches_the_platforms_and_the_badge(self) -> None:
        delivered = await _deliver_run(
            _run(workflow=True), _Seams(comms_text="Digest ready.", source=None)
        )

        assert delivered.to_platforms.await_args.kwargs["notification_text"] == "Digest ready."
        notify = delivered.notify.await_args.kwargs
        assert notify["msg_type"] == "final"
        assert notify["target"].conversation_id == "conv-1"
        assert notify["target"].user_id == "user-1"
        assert delivered.returned == ("Digest ready.", _saved(delivered).message_id)
        assert delivered.capture.call_args.args[2] == {"outcome": "reply", "delivery": "message"}

    async def test_a_failed_workflow_notifies_failure_but_posts_nothing_to_platforms(self) -> None:
        delivered = await _deliver_run(
            _run(workflow=True), _Seams(comms_text="It failed.", source=None), result_type="error"
        )

        delivered.to_platforms.assert_not_awaited()
        assert delivered.notify.await_args.kwargs["msg_type"] == "error"

    async def test_a_silent_workflow_posts_nothing_to_platforms(self) -> None:
        run = replace(_run(workflow=True), workflow_notify_on_completion=False)

        delivered = await _deliver_run(run, _Seams(comms_text="Digest ready.", source=None))

        delivered.to_platforms.assert_not_awaited()

    async def test_a_workflow_react_falls_back_to_the_text_ack(self) -> None:
        delivered = await _deliver_run(
            _run(workflow=True), _Seams(comms_text="REACT: 👍", source=None)
        )

        assert delivered.returned == (None, _saved(delivered).message_id)
        assert delivered.capture.call_args.args[2] == {
            "outcome": "react",
            "emoji": "👍",
            "delivery": "fallback_text",
        }


class TestAPlatformReaction:
    async def test_a_known_platform_id_attaches_a_native_reaction(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(
                comms_text="REACT: 👍", source=ConversationSource.WHATSAPP, platform_id="wamid.123"
            ),
        )

        delivered.lookup.assert_awaited_once_with("conv-1", "user-msg-1", "user-1")
        delivered.platform.assert_not_awaited()
        assert delivered.event["platform_reaction"] == "attached"

    async def test_no_platform_id_falls_back_to_a_text_bubble(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(comms_text="REACT: 👍", source=ConversationSource.WHATSAPP),
        )

        delivered.reaction.assert_not_awaited()
        delivered.platform.assert_awaited_once_with(
            ConversationSource.WHATSAPP, "user-1", "👍", conversation_id="conv-1"
        )
        assert delivered.event["platform_reaction"] == "fallback_text"


class TestLookupPlatformMessageId:
    async def test_no_user_message_means_nothing_to_anchor_to(self) -> None:
        with patch.object(rd, "conversation_repository") as repo:
            assert await rd._lookup_platform_message_id("conv-1", None, "user-1") is None
        repo.get_message.assert_not_called()

    async def test_the_answered_messages_platform_id_is_read_for_this_user(self) -> None:
        message = MessageModel(type="user", response="hi", date="2026-01-01")
        message.platform_message_id = "wamid.123"
        with patch.object(rd, "conversation_repository") as repo:
            repo.get_message = AsyncMock(return_value=message)
            found = await rd._lookup_platform_message_id("conv-1", "user-msg-1", "user-1")

        assert found == "wamid.123"
        repo.get_message.assert_awaited_once_with("conv-1", "user-msg-1", user_id="user-1")

    async def test_a_missing_message_has_no_platform_id(self) -> None:
        with patch.object(rd, "conversation_repository") as repo:
            repo.get_message = AsyncMock(return_value=None)
            assert await rd._lookup_platform_message_id("conv-1", "user-msg-1", "user-1") is None

    async def test_a_lookup_failure_is_logged_and_falls_back(self) -> None:
        async with captured_wide_event() as event:
            with patch.object(rd, "conversation_repository") as repo:
                repo.get_message = AsyncMock(side_effect=RuntimeError("mongo down"))
                found = await rd._lookup_platform_message_id("conv-1", "user-msg-1", "user-1")

        assert found is None
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} _lookup_platform_message_id: failed",
                "error": "mongo down",
            }
        ]


class TestBroadcastRetry:
    async def test_a_failed_push_is_retried_once_and_logged(self) -> None:
        event_out = {"type": "conversation.new_message"}
        ws = MagicMock()
        ws.broadcast_to_user = AsyncMock(side_effect=[RuntimeError("socket gone"), None])

        async with captured_wide_event() as event:
            with (
                patch.object(rd, "websocket_manager", ws),
                patch.object(rd, "WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS", 0),
            ):
                await rd._broadcast_message("user-1", event_out)

        assert ws.broadcast_to_user.await_count == 2
        ws.broadcast_to_user.assert_awaited_with("user-1", event_out)
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} _broadcast_message: broadcast attempt failed",
                "attempt": 1,
                "user_id": "user-1",
                "error": "socket gone",
            }
        ]


class TestWorkflowNotificationIsTraceable:
    async def test_the_dispatch_log_names_the_message_the_badge_opens(self) -> None:
        """Operators trace a workflow badge back to its saved message by this id."""
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="Digest ready."
            ),
            patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(rd, "deliver_result_to_platforms", new_callable=AsyncMock),
            patch(
                "app.services.workflow.notifications.send_workflow_completion_notification",
                new_callable=AsyncMock,
            ) as completion,
            patch.object(rd, "log") as log_mock,
        ):
            _, message_id = await rd.deliver_result(
                _run(workflow=True), result_text="raw", result_type="final", tool_data=None
            )

        completion.assert_awaited_once_with(
            workflow_id="wf-1",
            workflow_title="Morning digest",
            conversation_id="conv-1",
            user_id="user-1",
        )
        dispatched = [
            call.kwargs
            for call in log_mock.info.call_args_list
            if "workflow notification dispatched" in call.args[0]
        ]
        assert dispatched == [{"workflow_id": "wf-1", "message_id": message_id}]
