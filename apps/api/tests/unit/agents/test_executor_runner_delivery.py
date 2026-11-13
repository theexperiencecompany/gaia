"""Unit tests for background-executor message delivery.

Two invariants, both owned by result_delivery.py:

* a background result is delivered over EXACTLY ONE transport, chosen by the
  conversation's own source — bot conversations to their platform, everything
  else over WebSocket — and the message is always persisted;
* a queued run's message is keyed on its task id so the client reconciles it
  onto its placeholder, while a live run's mints a fresh id.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
from prometheus_client import REGISTRY
import pytest

from app.agents.core.background import (
    executor_runner as er,
    result_delivery as rd,
    workflow_platform_delivery as wpd,
)
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    TodoRun,
)
from app.agents.prompts.comms_prompts import (
    INTERACTIVE_DELIVERY_NOTE,
    PLATFORM_DELIVERY_NOTE,
    SILENCE_NOTE,
)
from app.constants.chat import CONVERSATION_MAX_MESSAGES
from app.constants.executor import (
    EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE,
    EXECUTOR_NARRATION_FAILED_MESSAGE,
)
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.constants.todos import TODO_CONVERSATION_MAX_MESSAGES
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationSource, MessageKind, MessageModel, ToolDataEntry
from app.models.message_models import ReplyToMessageData
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.delivery.chat_channel import InApp
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunFailed, AgentRunStarted
from shared.py.analytics.catalog.chat import ChatBackgroundUpdateResolved
from shared.py.analytics.catalog.workflows import WorkflowResultDelivered
from shared.py.wide_events import log
from tests.helpers import captured_wide_event

# A run says it lives in Redis while it runs: give it a per-test Redis, never the ambient one.
pytestmark = pytest.mark.usefixtures("fake_redis")

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NO_CHAT_APP = InApp(reason="no_chat_app")


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
        user=AuthenticatedUser(user_id=USER_ID),
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


class TestABotReplyGeneratesNoFollowUps:
    """No bot renders follow-up chips, so a bot reply never pays for the second LLM call."""

    async def _deliver_to_telegram(self, *, delivered: bool):
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="voiced"
            ),
            patch.object(
                rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[]
            ) as inline,
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
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
        return inline, platform, deferred, save

    @pytest.mark.regression
    @pytest.mark.parametrize("delivered", [True, False])
    async def test_neither_inline_nor_deferred_follow_ups_run(self, delivered: bool) -> None:
        inline, platform, deferred, save = await self._deliver_to_telegram(delivered=delivered)

        platform.assert_awaited_once()
        inline.assert_not_awaited()
        deferred.assert_not_called()
        assert save.await_args.args[0].messages[0].follow_up_actions is None


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
            patch.object(wpd, "resolve_proactive_target", AsyncMock(return_value=NO_CHAT_APP)),
            patch.object(wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)),
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

        assert save.await_args.kwargs["user"] == AuthenticatedUser(user_id=USER_ID)

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
            patch.object(
                rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None
            ) as conversation_source,
            patch.object(
                wpd, "resolve_proactive_target", AsyncMock(return_value=NO_CHAT_APP)
            ) as resolve_target,
            patch.object(
                wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)
            ) as deliver,
            patch.object(wpd, "capture") as capture,
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock) as notify,
        ):
            await rd.deliver_result(
                _run(workflow=True), result_text="done", result_type="final", tool_data=None
            )

        capture.assert_called_once_with(
            UserId(USER_ID),
            WorkflowResultDelivered(
                workflow_id="wf-1",
                outcome="delivered",
                destination="in_app",
                destination_basis="no_chat_app",
            ),
        )
        conversation_source.assert_awaited_once_with("conv-1", USER_ID)
        resolve_target.assert_awaited_once_with(USER_ID)
        deliver.assert_awaited_once()
        kwargs = deliver.await_args.kwargs
        assert kwargs["user"] == AuthenticatedUser(user_id=USER_ID)
        assert kwargs["user_id"] == USER_ID
        assert kwargs["origin"] == ('workflow "Morning digest" (id wf-1), tracked todo (id todo-9)')
        assert kwargs["target"] is NO_CHAT_APP
        notify.assert_awaited_once()  # the in-app badge still fires alongside

    async def test_a_failed_target_lookup_loses_only_the_chat_app_copy(self) -> None:
        """Regression: the lookup ran before the save, so its failure dropped the saved result and the badge."""
        with (
            patch.object(
                rd, "narrate_executor_result", new_callable=AsyncMock, return_value="done"
            ),
            patch.object(rd, "_safe_inline_follow_ups", new_callable=AsyncMock, return_value=[]),
            patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
            patch.object(rd, "_get_conversation_source", new_callable=AsyncMock, return_value=None),
            patch.object(
                wpd,
                "resolve_proactive_target",
                AsyncMock(side_effect=ConnectionError("mongo down")),
            ),
            patch.object(
                wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)
            ) as deliver,
            patch.object(rd, "_dispatch_workflow_notification", new_callable=AsyncMock) as notify,
        ):
            async with captured_wide_event() as event:
                narrated, message_id = await rd.deliver_result(
                    _run(workflow=True), result_text="done", result_type="final", tool_data=None
                )

        save.assert_awaited_once()
        notify.assert_awaited_once()
        deliver.assert_not_awaited()
        assert (narrated, message_id is not None) == ("done", True)
        assert event["errors"] == [
            {
                "msg": f"{LogTag.AGENT} workflow result: chat app lookup failed, not sent to the chat app",
                "workflow_id": "wf-1",
                "error": "mongo down",
                "error_type": "ConnectionError",
            }
        ]


class TestGetConversationSource:
    """The authoritative routing key: the conversation's persisted source.

    Coercion of a stored string into the enum now lives in the repository's
    get_source (covered by the repository contract tests); here we assert the
    delivery wrapper passes it through, scopes by owner, and fails soft.
    """

    async def test_returns_source_from_repository(self) -> None:
        with patch.object(conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WHATSAPP
            src = await rd._get_conversation_source("conv-1", USER_ID)
        assert src is ConversationSource.WHATSAPP

    async def test_query_is_scoped_to_conversation_and_owner(self) -> None:
        with patch.object(conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = ConversationSource.WEB
            await rd._get_conversation_source("conv-1", USER_ID)
        # must be scoped by BOTH conversation_id and user_id (no cross-user read)
        assert get.await_args.args[0] == "conv-1"
        assert get.await_args.kwargs["user_id"] == USER_ID

    async def test_missing_conversation_returns_none(self) -> None:
        with patch.object(conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.return_value = None
            assert await rd._get_conversation_source("conv-1", USER_ID) is None

    async def test_db_error_returns_none(self) -> None:
        with patch.object(conversation_repository, "get_source", new_callable=AsyncMock) as get:
            get.side_effect = RuntimeError("mongo down")
            assert await rd._get_conversation_source("conv-1", USER_ID) is None


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

    @pytest.mark.parametrize(
        ("todo_run", "cap"),
        [
            (None, CONVERSATION_MAX_MESSAGES),
            (
                TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True),
                TODO_CONVERSATION_MAX_MESSAGES,
            ),
        ],
        ids=["chat", "todo-chat"],
    )
    async def test_a_stopped_runs_cards_keep_the_conversations_cap(
        self, todo_run: TodoRun | None, cap: int
    ) -> None:
        """Regression: an explicit None for a plain chat switched off the cap every conversation has."""
        run = replace(
            _run(RunKind.QUEUED, stream_id="queued_s1", task_id="task-9"), todo_run=todo_run
        )

        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd.persist_cancelled_run(run, CARDS)

        assert save.await_args.kwargs["max_messages"] == cap

    async def test_a_bot_reply_keeps_the_conversations_cap(self) -> None:
        bot_message = MessageModel(type="bot", response="hi")
        with patch.object(rd, "update_messages", new_callable=AsyncMock) as save:
            await rd._save_message("conv-1", AuthenticatedUser(user_id=USER_ID), bot_message)

        assert save.await_args.kwargs["max_messages"] == CONVERSATION_MAX_MESSAGES

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
        ):
            await rd._narrate_result(_run(), "raw", "final", "")
        assert _narration_count("success") == before + 1

    async def test_save_message_records_span(self) -> None:
        before = _persist_count("save_bot_message")
        bot_message = MessageModel(type="bot", response="hi", date="2026-01-01")
        with patch.object(rd, "update_messages", new_callable=AsyncMock):
            assert (
                await rd._save_message("conv-1", AuthenticatedUser(user_id=USER_ID), bot_message)
                is True
            )
        assert _persist_count("save_bot_message") == before + 1

    async def test_cancelled_persist_records_exact_seconds(self) -> None:
        # Pinned clock: the persisted sample must be the elapsed subtraction in
        # SECONDS. A sign error (end + start) would record 40.75 here.
        run = _run(RunKind.QUEUED, stream_id="queued_lat2", task_id="task-lat2")
        labels = {"op": "cancelled_cards"}
        before = REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) or 0.0
        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(time, "perf_counter", side_effect=[20.0, 20.75]),
        ):
            await rd.persist_cancelled_run(run, CARDS)
        assert REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) == before + 0.75

    async def test_save_message_records_exact_seconds(self) -> None:
        labels = {"op": "save_bot_message"}
        before = REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) or 0.0
        bot_message = MessageModel(type="bot", response="hi", date="2026-01-01")
        with (
            patch.object(rd, "update_messages", new_callable=AsyncMock),
            patch.object(time, "perf_counter", side_effect=[7.0, 7.25]),
        ):
            assert (
                await rd._save_message("conv-1", AuthenticatedUser(user_id=USER_ID), bot_message)
                is True
            )
        assert REGISTRY.get_sample_value("delivery_persist_seconds_sum", labels) == before + 0.25

    async def test_narration_records_exact_seconds(self) -> None:
        labels = {"status": "success"}
        before = REGISTRY.get_sample_value("delivery_narration_seconds_sum", labels) or 0.0
        with (
            patch.object(rd, "narrate_executor_result", new_callable=AsyncMock, return_value="v"),
            patch.object(time, "perf_counter", side_effect=[3.0, 3.5]),
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
            patch.object(time, "perf_counter", side_effect=[3.0, 3.5]),
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

        assert save.await_args.kwargs["user"] == AuthenticatedUser(user_id=USER_ID)

    async def test_live_run_never_self_attaches_cards(self) -> None:
        """The comms stream owns a live run's cards, so its snapshot is None — delivery must not invent tool_data."""
        run = _run(RunKind.LIVE, stream_id="live_s1", task_id="task-9")

        save, ws = await self._deliver_with_cards(run, None)

        saved = save.await_args.args[0].messages[0]
        assert not saved.tool_data
        assert saved.message_id != "task-9"  # no placeholder to reconcile with
        assert "tool_data" not in ws.await_args.args[1]["message"]

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
        user_id: str | None = USER_ID,
        error_type: str | None = None,
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
            patch("app.services.analytics_service.capture") as mock_capture,
            patch.object(
                er,
                "_execute_executor",
                new_callable=AsyncMock,
                return_value=_ExecutorResult(result_text, result_type, error_type=error_type),
            ),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": user_id})
        return mock_capture

    async def test_started_and_completed_on_final(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final")

        events = [type(c.args[1]) for c in mock_capture.call_args_list]
        assert events == [AgentRunStarted, AgentRunCompleted]
        assert mock_capture.call_args_list[0].args == (
            UserId(USER_ID),
            AgentRunStarted(
                agent="executor", mode="background", conversation_id="conv-1", task_id="task-1"
            ),
        )
        # The TERMINAL event needs the same scrutiny as the opening one: it was
        # asserted only by name, so its user id and payload could both go null
        # without a test noticing.
        assert mock_capture.call_args_list[1].args[0] == UserId(USER_ID)
        terminal = mock_capture.call_args_list[1].args[1]
        assert terminal.agent == "executor"
        assert terminal.mode == "background"
        assert terminal.conversation_id == "conv-1"
        assert terminal.task_id == "task-1"
        assert terminal.queued is False
        assert terminal.executor_active_ms is not None
        assert terminal.executor_active_ms >= 0.0
        # A resumed segment re-enters with the same task, so the terminal is keyed on it.
        assert mock_capture.call_args_list[0].kwargs["dedupe"] is None
        assert mock_capture.call_args_list[1].kwargs["dedupe"].key == "task-1"

    async def test_a_run_without_a_task_keys_its_terminal_on_the_stream(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final", task_id=None)

        assert mock_capture.call_args_list[1].kwargs["dedupe"].key == "stream-1"

    async def test_failed_on_error_result(self) -> None:
        mock_capture = await self._run_lifecycle("it broke", "error", error_type="RuntimeError")

        events = [type(c.args[1]) for c in mock_capture.call_args_list]
        assert events == [AgentRunStarted, AgentRunFailed]
        assert mock_capture.call_args_list[1].args[0] == UserId(USER_ID)
        terminal = mock_capture.call_args_list[1].args[1]
        assert terminal.agent == "executor"
        assert terminal.task_id == "task-1"
        assert terminal.queued is False
        assert terminal.executor_active_ms is not None
        assert terminal.executor_active_ms >= 0.0
        assert terminal.reason == "RuntimeError"

    async def test_a_run_with_no_user_id_captures_nothing(self) -> None:
        """run.user with no id must produce no events at all — the guard relies on a "" default staying falsy."""
        mock_capture = await self._run_lifecycle("done", "final", user_id=None)

        mock_capture.assert_not_called()

    async def test_no_user_id_skips_events(self) -> None:
        mock_capture = await self._run_lifecycle("done", "final", user_id="")
        mock_capture.assert_not_called()


def _approval_card(approval_id: str, status: str, **extra: object) -> ToolDataEntry:
    return ToolDataEntry(
        tool_name=APPROVAL_REQUEST_TOOL_NAME,
        data={"approval_id": approval_id, "status": status, **extra},
    )


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
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.QUEUED,
            task_id="task-7",
            user_message_id="user-msg-1",
        )

        message = await self._deliver_run(run)

        assert message["replyToMessage"]["id"] == "user-msg-1"


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
        user_id: str = USER_ID,
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
            "configurable": {"user_id": USER_ID, "session_id": "conv-1"}
        }

    async def test_a_conversationless_run_still_names_its_user(self) -> None:
        gen = await self._build(conversation_id=None)

        assert gen.call_args.args[2] == {"configurable": {"user_id": USER_ID, "session_id": None}}

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

        assert gen.call_args.args[1] == USER_ID

    async def test_a_non_final_result_asks_for_nothing(self) -> None:
        """An error or intermediate ack gets no suggestions, and costs no call."""
        gen = await self._build(msg_type="error")

        assert self.result == []
        gen.assert_not_awaited()


def _quoting_run(user: AuthenticatedUser | None = None) -> ExecutorRun:
    """Build a queued run that answers a specific user message, so it quotes it."""
    return ExecutorRun(
        stream_id="",
        conversation_id="conv-1",
        user=AuthenticatedUser(user_id=USER_ID) if user is None else user,
        kind=RunKind.QUEUED,
        task_id="task-7",
        user_message_id="user-msg-1",
    )


def _target(**over) -> rd._DeliveryTarget:
    """Build the delivery target a quoting queued run produces."""
    fields: dict = {
        "user_id": USER_ID,
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
    decides whose it is, and the preamble decides the voice (a workflow's here).
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
            preamble: str,
        ) -> str:
            calls.append(((result_text, msg_type, conversation_id, user), {"preamble": preamble}))
            return "voiced"

        with patch.object(rd, "narrate_executor_result", new=_record):
            narrated = await rd._narrate_result(
                _run(workflow=True), "raw text", "final", "handed back by the subagent"
            )

        assert narrated == "voiced"
        assert calls == [
            (
                ("raw text", "final", "conv-1", AuthenticatedUser(user_id=USER_ID)),
                {"preamble": PLATFORM_DELIVERY_NOTE},
            )
        ]


class TestBuildBotMessageShape:
    """The saved-and-delivered bubble: the client renders on type and orders the thread on date, both load-bearing."""

    def test_it_is_a_bot_bubble_carrying_the_voiced_text(self) -> None:
        message = rd._build_bot_message(_run(), "voiced", None)

        assert message.type == "bot"
        assert message.response == "voiced"

    def test_the_timestamp_is_a_real_utc_instant(self) -> None:
        """A naive local stamp sorts the message wrong in a UTC thread; a missing one drops it out of the ordering entirely."""
        before = datetime.now(UTC)
        message = rd._build_bot_message(_run(), "voiced", None)
        after = datetime.now(UTC)

        assert message.date.endswith("+00:00"), "must be an explicit UTC offset, not local time"
        assert before <= datetime.fromisoformat(message.date) <= after


class TestAttachReplyQuoteLookup:
    """The quote the user sees above a queued answer.

    It is read back from Mongo by (conversation, message, owner); any one of
    those three being wrong either reads a stranger's message or reads nothing
    and silently quotes an empty bubble.
    """

    async def _attach(self, run: ExecutorRun):
        bot_message = MessageModel(type="bot", response="voiced", date="2026-01-01")
        with patch.object(
            conversation_repository,
            "get_message",
            new_callable=AsyncMock,
            return_value=MessageModel(type="user", response="what I asked", date="2026-01-01"),
        ) as get:
            result = await rd._attach_reply_quote(run, bot_message)
        return result, get, bot_message

    async def test_the_lookup_is_scoped_to_this_conversation_message_and_owner(self) -> None:
        result, get, _bot_message = await self._attach(_quoting_run())

        assert get.await_args.args == ("conv-1", "user-msg-1")
        assert get.await_args.kwargs == {"user_id": USER_ID}
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

        assert ws.await_args.args[0] == USER_ID

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

        assert narrate.await_args.kwargs["preamble"].startswith("handed back by the subagent")


class TestDeliveryPreamble:
    """Which delivery instructions comms writes a run's reply under."""

    CARD_NOTE = "<returned_to_frontend>a card is on screen</returned_to_frontend>"

    def test_a_workflow_result_is_restated_in_full_with_no_card_note(self) -> None:
        """The card note would tell comms not to list data that has no card to fall back on."""
        assert rd._delivery_preamble(_run(workflow=True), self.CARD_NOTE) == (
            PLATFORM_DELIVERY_NOTE
        )

    def test_an_interactive_result_reads_the_card_note_before_the_split_rule(self) -> None:
        assert rd._delivery_preamble(_run(), self.CARD_NOTE) == (
            self.CARD_NOTE + INTERACTIVE_DELIVERY_NOTE + SILENCE_NOTE
        )


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
            patch.object(wpd, "resolve_proactive_target", AsyncMock(return_value=NO_CHAT_APP)),
            patch.object(wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)),
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
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.LIVE,
            task_id="task-1",
            user_message_id=None,
        )
        with (
            patch("app.services.analytics_service.capture"),
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
        return dict(boundary.call_args.kwargs)

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
            user=AuthenticatedUser(user_id=USER_ID),
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
            patch("app.services.analytics_service.capture"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(
                run, "do things", {"user_id": USER_ID, "workflow_id": "wf-9"}
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
            user=AuthenticatedUser(user_id=USER_ID),
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
            patch("app.services.analytics_service.capture"),
            patch.object(er, "_execute_executor", side_effect=capture),
            patch.object(er, "_finalize_executor_run", new_callable=AsyncMock),
        ):
            await er.run_executor_background(run, "do things", {"user_id": USER_ID})

        assert seen["workflow"] is None


class TestCommsDirectiveDelivery:
    """Comms can answer a not-mention-worthy background update with a control line: SILENCE (deliver nothing) or REACT (a one-emoji acknowledgment)."""

    async def test_silence_delivers_nothing_on_any_surface(self) -> None:
        with patch.object(rd, "capture") as capture:
            save, platform, ws = await _deliver(
                ConversationSource.WHATSAPP,
                comms_text="<SILENCE>routine calendar refresh</SILENCE>",
            )
        save.assert_not_awaited()
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        # Attributed to the run's owner, or the funnel joins nobody. One resolution
        # event per update, tagged with the outcome; the reason text never leaves.
        capture.assert_called_once()
        assert capture.call_args.args == (
            UserId(USER_ID),
            ChatBackgroundUpdateResolved(outcome="silence"),
        )

    @pytest.mark.regression
    async def test_a_message_with_a_trailing_directive_delivers_only_the_message(self) -> None:
        message = "Your passport expires in 13 days."
        save, platform, _ws = await _deliver(
            ConversationSource.TELEGRAM,
            comms_text=f"{message}{NEW_MESSAGE_BREAKER}<EMOJI>👍</EMOJI>",
        )
        assert platform.await_args.args[2] == message
        saved = save.await_args.args[0].messages[0]
        assert (saved.response, saved.kind) == (message, MessageKind.TEXT)

    async def test_silence_on_web_broadcasts_nothing(self) -> None:
        save, platform, ws = await _deliver(
            ConversationSource.WEB, comms_text="<SILENCE>nothing new</SILENCE>"
        )
        save.assert_not_awaited()
        ws.assert_not_awaited()
        platform.assert_not_awaited()

    async def test_react_delivers_the_emoji_as_the_message_on_a_bot(self) -> None:
        with patch.object(rd, "capture") as capture:
            save, platform, _ws = await _deliver(
                ConversationSource.WHATSAPP, comms_text="<EMOJI>👍</EMOJI>"
            )
        platform.assert_awaited_once()
        assert platform.await_args.args[2] == "👍"
        capture.assert_called_once()
        assert capture.call_args.args == (
            UserId(USER_ID),
            ChatBackgroundUpdateResolved(outcome="react", emoji="👍", delivery="fallback_text"),
        )
        # The ack intent is recorded on the persisted message, not left to be
        # reverse-engineered from the body being emoji-only.
        assert save.await_args.args[0].messages[0].kind is MessageKind.EMOJI_ACK

    async def test_react_delivers_the_emoji_over_websocket_on_web(self) -> None:
        save, _platform, ws = await _deliver(ConversationSource.WEB, comms_text="<EMOJI>✅</EMOJI>")
        ws.assert_awaited_once()
        assert ws.await_args.args[1]["message"]["response"] == "✅"
        assert save.await_args.args[0].messages[0].kind is MessageKind.EMOJI_ACK

    async def test_react_attaches_a_native_reaction_when_the_platform_id_is_known(
        self,
    ) -> None:
        """The recorded platform id turns the ack into a real reaction: the reaction envelope goes out and no text bubble is sent."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                return_value="<EMOJI>👍</EMOJI>",
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
            patch.object(rd, "capture") as capture,
        ):
            await rd.deliver_result(run, result_text="raw", result_type="final", tool_data=None)
        react.assert_awaited_once_with(
            ConversationSource.WHATSAPP,
            USER_ID,
            "wamid.123",
            "👍",
            conversation_id="conv-1",
        )
        platform.assert_not_awaited()
        ws.assert_not_awaited()
        # The ack is still persisted (history/audit), targeted at the GAIA
        # message it answers so every surface can render it as a reaction.
        saved = save.await_args.args[0].messages[0]
        assert saved.kind is MessageKind.EMOJI_ACK
        assert saved.response == "👍"
        assert saved.reacts_to_message_id == "user-msg-1"
        assert capture.call_args.args[1] == ChatBackgroundUpdateResolved(
            outcome="react", emoji="👍", delivery="reaction"
        )

    async def test_react_falls_back_to_text_without_a_platform_id(self) -> None:
        """Older turns and non-bot triggers have no recorded platform id: the emoji goes out as a text bubble and the ack is never lost."""
        run = replace(_run(), user_message_id="user-msg-1")
        with (
            patch.object(
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                return_value="<EMOJI>👍</EMOJI>",
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
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                return_value="<EMOJI>✅</EMOJI>",
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
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                return_value="<EMOJI>✅</EMOJI>",
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
                rd,
                "narrate_executor_result",
                new_callable=AsyncMock,
                return_value="<EMOJI>✅</EMOJI>",
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
        with patch.object(rd, "capture") as capture:
            save, platform, _ws = await _deliver(
                ConversationSource.WHATSAPP, comms_text="Booked your 9am flight."
            )
        assert platform.await_args.args[2] == "Booked your 9am flight."
        # The baseline outcome is captured too, so silence/react rates have a
        # denominator; an ordinary message stays MessageKind.TEXT.
        assert capture.call_args.args[1] == ChatBackgroundUpdateResolved(
            outcome="reply", delivery="message"
        )
        assert save.await_args.args[0].messages[0].kind is MessageKind.TEXT


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
            patch.object(rd, "capture") as capture,
            patch.object(wpd, "resolve_proactive_target", AsyncMock(return_value=NO_CHAT_APP)),
            patch.object(
                wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)
            ) as to_platforms,
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
                "<SILENCE>routine refresh</SILENCE>",
                {"comms_delivery": "silenced", "silence_reason": "routine refresh"},
            ),
            ("<EMOJI>👍</EMOJI>", {"comms_delivery": "reacted"}),
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
    """One chat:background_update_resolved per update, deduped on the run it resolved."""

    async def test_a_queued_run_dedupes_on_its_task_and_dispatch_time(self) -> None:
        run = _run(RunKind.QUEUED, task_id="task-7")
        delivered = await _deliver_run(run, _Seams(comms_text="Done.", source=None))

        assert delivered.capture.call_args.kwargs == {
            "dedupe": Dedupe(key="task-7", occurred_at=run.dispatched_at)
        }

    async def test_a_run_with_no_id_is_not_deduped_onto_its_conversation(self) -> None:
        """Every update in a conversation would otherwise collapse into one row."""
        delivered = await _deliver_run(_run(), _Seams(comms_text="Done.", source=None))

        assert delivered.capture.call_args.kwargs == {"dedupe": None}

    async def test_a_web_react_lands_as_a_badge(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(comms_text="<EMOJI>✅</EMOJI>", source=None),
        )

        assert delivered.capture.call_args.args[1] == ChatBackgroundUpdateResolved(
            outcome="react", emoji="✅", delivery="badge"
        )

    async def test_a_web_reply_is_delivered_over_the_websocket(self) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text="Done.", source=ConversationSource.WEB)
        )

        assert delivered.event["result_delivery"]["transport"] == "websocket"
        assert delivered.event["result_delivery"]["delivered"] is True


class TestInlineFollowUpsOnlyWhereNothingWaits:
    """Only a workflow attaches follow-ups inline; web defers them; bots and reactions get none."""

    async def test_a_bot_reaction_generates_no_follow_ups(self) -> None:
        delivered = await _deliver_run(
            _run(), _Seams(comms_text="<EMOJI>👍</EMOJI>", source=ConversationSource.WHATSAPP)
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
        delivered = await _deliver_run(_run(), _Seams(comms_text="<EMOJI>✅</EMOJI>", source=None))

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
        assert notify["target"].user_id == USER_ID
        assert delivered.returned == ("Digest ready.", _saved(delivered).message_id)
        assert delivered.capture.call_args.args[1] == ChatBackgroundUpdateResolved(
            outcome="reply", delivery="message"
        )

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
            _run(workflow=True), _Seams(comms_text="<EMOJI>👍</EMOJI>", source=None)
        )

        assert delivered.returned == (None, _saved(delivered).message_id)
        assert delivered.capture.call_args.args[1] == ChatBackgroundUpdateResolved(
            outcome="react", emoji="👍", delivery="fallback_text"
        )


class TestAPlatformReaction:
    async def test_a_known_platform_id_attaches_a_native_reaction(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(
                comms_text="<EMOJI>👍</EMOJI>",
                source=ConversationSource.WHATSAPP,
                platform_id="wamid.123",
            ),
        )

        delivered.lookup.assert_awaited_once_with("conv-1", "user-msg-1", USER_ID)
        delivered.platform.assert_not_awaited()
        assert delivered.event["platform_reaction"] == "attached"

    async def test_no_platform_id_falls_back_to_a_text_bubble(self) -> None:
        delivered = await _deliver_run(
            replace(_run(), user_message_id="user-msg-1"),
            _Seams(comms_text="<EMOJI>👍</EMOJI>", source=ConversationSource.WHATSAPP),
        )

        delivered.reaction.assert_not_awaited()
        delivered.platform.assert_awaited_once_with(
            ConversationSource.WHATSAPP, USER_ID, "👍", conversation_id="conv-1"
        )
        assert delivered.event["platform_reaction"] == "fallback_text"


class TestLookupPlatformMessageId:
    async def test_no_user_message_means_nothing_to_anchor_to(self) -> None:
        with patch.object(rd, "conversation_repository") as repo:
            assert await rd._lookup_platform_message_id("conv-1", None, USER_ID) is None
        repo.get_message.assert_not_called()

    async def test_the_answered_messages_platform_id_is_read_for_this_user(self) -> None:
        message = MessageModel(type="user", response="hi", date="2026-01-01")
        message.platform_message_id = "wamid.123"
        with patch.object(rd, "conversation_repository") as repo:
            repo.get_message = AsyncMock(return_value=message)
            found = await rd._lookup_platform_message_id("conv-1", "user-msg-1", USER_ID)

        assert found == "wamid.123"
        repo.get_message.assert_awaited_once_with("conv-1", "user-msg-1", user_id=USER_ID)

    async def test_a_missing_message_has_no_platform_id(self) -> None:
        with patch.object(rd, "conversation_repository") as repo:
            repo.get_message = AsyncMock(return_value=None)
            assert await rd._lookup_platform_message_id("conv-1", "user-msg-1", USER_ID) is None

    async def test_a_lookup_failure_is_logged_and_falls_back(self) -> None:
        async with captured_wide_event() as event:
            with patch.object(rd, "conversation_repository") as repo:
                repo.get_message = AsyncMock(side_effect=RuntimeError("mongo down"))
                found = await rd._lookup_platform_message_id("conv-1", "user-msg-1", USER_ID)

        assert found is None
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} _lookup_platform_message_id: failed",
                "error": "mongo down",
            }
        ]


class TestBroadcastRetry:
    async def test_a_failed_push_is_retried_once_and_logged(self) -> None:
        event_out: dict[str, object] = {"type": "conversation.new_message"}
        ws = MagicMock()
        ws.broadcast_to_user = AsyncMock(side_effect=[RuntimeError("socket gone"), None])

        async with captured_wide_event() as event:
            with (
                patch.object(rd, "websocket_manager", ws),
                patch.object(rd, "WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS", 0),
            ):
                await rd._broadcast_message(USER_ID, event_out)

        assert ws.broadcast_to_user.await_count == 2
        ws.broadcast_to_user.assert_awaited_with(USER_ID, event_out)
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} _broadcast_message: broadcast attempt failed",
                "attempt": 1,
                "user_id": USER_ID,
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
            patch.object(wpd, "resolve_proactive_target", AsyncMock(return_value=NO_CHAT_APP)),
            patch.object(wpd, "deliver_result_to_platforms", AsyncMock(return_value=None)),
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
            user_id=USER_ID,
        )
        dispatched = [
            call.kwargs
            for call in log_mock.info.call_args_list
            if "workflow notification dispatched" in call.args[0]
        ]
        assert dispatched == [{"workflow_id": "wf-1", "message_id": message_id}]
