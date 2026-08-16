"""Behavior tests for app.agents.core.background.comms_narrator.

Locks: the executor result is re-voiced through the comms graph as a
HumanMessage with the right internal marker (never a SystemMessage — the
regression the comment block warns about), the platform-delivery note is
prepended for workflow delivery, and every degradation path returns an empty
string instead of crashing the caller. Also the cancellation record appended
to the comms checkpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_executor_cancellation,
)
from app.agents.core.graph_manager import GraphUnavailableError
from app.agents.prompts.comms_prompts import PLATFORM_DELIVERY_NOTE
from app.constants.agents import (
    EXECUTOR_CANCELLED_MARKER,
    EXECUTOR_ERROR_MARKER,
    EXECUTOR_RESULT_MARKER,
)
from app.constants.general import NEW_MESSAGE_BREAKER

MODULE = "app.agents.core.background.comms_narrator"


def _provider_error() -> ConnectionError:
    return ConnectionError("402 insufficient credits")


USER: dict = {"user_id": "user-1", "email": "u@gaia.local"}
CONVERSATION_ID = "conv-1"
RESULT_TEXT = f"Downloaded the report.{NEW_MESSAGE_BREAKER}It has 3 pages."


def _fake_comms_graph() -> MagicMock:
    graph = MagicMock()
    graph.aupdate_state = AsyncMock()
    return graph


def _patch_graph(graph: MagicMock) -> MagicMock:
    return patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph))


class TestNarrateExecutorResult:
    async def test_result_is_revoiced_through_the_comms_graph(self) -> None:
        graph = _fake_comms_graph()
        with (
            _patch_graph(graph),
            patch(
                f"{MODULE}.execute_graph_silent",
                AsyncMock(return_value=(f"Done. {RESULT_TEXT}", {})),
            ) as silent,
        ):
            text = await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER)

        assert text == f"Done. {RESULT_TEXT}"
        assert silent.await_args.args[0] is graph
        initial = silent.await_args.args[1]
        message = initial["messages"][0]
        assert isinstance(message, HumanMessage)
        assert message.name == "background_executor"
        assert message.content == f"{EXECUTOR_RESULT_MARKER}\n{RESULT_TEXT}"
        config = silent.await_args.args[2]
        assert config["configurable"]["conversation_id"] == CONVERSATION_ID

    async def test_error_type_uses_the_error_marker(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result("boom", "error", CONVERSATION_ID, USER)

        initial = silent.await_args.args[1]
        assert initial["messages"][0].content == f"{EXECUTOR_ERROR_MARKER}\nboom"

    async def test_workflow_delivery_prepends_the_platform_delivery_note(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result(
                RESULT_TEXT,
                "result",
                CONVERSATION_ID,
                USER,
                returned_note="[CARD_NOTE]",
                workflow_id="wf-1",
            )

        content = silent.await_args.args[1]["messages"][0].content
        assert content.startswith(PLATFORM_DELIVERY_NOTE)
        assert EXECUTOR_RESULT_MARKER in content

    async def test_interactive_chat_prepends_the_returned_note(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result(
                RESULT_TEXT, "result", CONVERSATION_ID, USER, returned_note="[CARD_NOTE]"
            )

        content = silent.await_args.args[1]["messages"][0].content
        assert content == f"[CARD_NOTE]{EXECUTOR_RESULT_MARKER}\n{RESULT_TEXT}"

    async def test_parroted_internal_markers_are_stripped(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent",
                AsyncMock(return_value=(f"{EXECUTOR_RESULT_MARKER} done", {})),
            ),
        ):
            text = await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER)

        assert text == "done"

    async def test_unavailable_graph_drops_narration_without_crashing(self) -> None:
        with patch(
            f"{MODULE}.GraphManager.get_graph",
            AsyncMock(side_effect=GraphUnavailableError("comms_agent", "no graph")),
        ):
            assert await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER) == ""

    async def test_narration_failure_returns_empty_string(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(f"{MODULE}.execute_graph_silent", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            assert await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER) == ""

    @pytest.mark.regression
    async def test_provider_failure_retries_the_narration_on_the_fallback_provider(self) -> None:
        silent = AsyncMock(side_effect=[_provider_error(), ("revoiced on fallback", {})])
        with (
            _patch_graph(_fake_comms_graph()),
            patch(f"{MODULE}.execute_graph_silent", silent),
            patch(f"{MODULE}.pin_fallback_provider", return_value=True) as pin,
            patch(f"{MODULE}.log") as mock_log,
        ):
            text = await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER)

        assert text == "revoiced on fallback"
        assert silent.await_count == 2
        first_config = silent.await_args_list[0].args[2]
        pin.assert_called_once_with(first_config["configurable"])
        mock_log.warning.assert_called_once()
        message, kwargs = mock_log.warning.call_args.args[0], mock_log.warning.call_args.kwargs
        assert "retrying on fallback" in message
        assert kwargs == {
            "error": "402 insufficient credits",
            "error_type": "ConnectionError",
            "conversation_id": CONVERSATION_ID,
        }

    async def test_provider_failure_with_no_fallback_provider_returns_empty_string(self) -> None:
        silent = AsyncMock(side_effect=_provider_error())
        with (
            _patch_graph(_fake_comms_graph()),
            patch(f"{MODULE}.execute_graph_silent", silent),
            patch(f"{MODULE}.pin_fallback_provider", return_value=False),
        ):
            assert await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER) == ""
        assert silent.await_count == 1

    async def test_programming_errors_are_not_retried_on_another_provider(self) -> None:
        silent = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            _patch_graph(_fake_comms_graph()),
            patch(f"{MODULE}.execute_graph_silent", silent),
            patch(f"{MODULE}.pin_fallback_provider", return_value=True) as pin,
        ):
            assert await narrate_executor_result(RESULT_TEXT, "result", CONVERSATION_ID, USER) == ""
        assert silent.await_count == 1
        pin.assert_not_called()


class TestRecordExecutorCancellation:
    async def test_cancellation_marker_is_appended_to_the_checkpoint(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, "task-42", "send the email")

        graph.aupdate_state.assert_awaited_once()
        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        assert call.kwargs["as_node"] == "tools"
        messages = call.args[1]["messages"]
        assert len(messages) == 1
        content = messages[0].content
        assert content.startswith(EXECUTOR_CANCELLED_MARKER)
        assert "task-42" in content
        assert "did NOT finish" in content

    async def test_unknown_task_id_is_named_as_unknown(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, None, "send the email")

        content = graph.aupdate_state.await_args.args[1]["messages"][0].content
        assert "(unknown id)" in content

    async def test_failure_to_record_is_swallowed(self) -> None:
        graph = _fake_comms_graph()
        graph.aupdate_state = AsyncMock(side_effect=RuntimeError("checkpoint down"))
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, "task-42", "send the email")
