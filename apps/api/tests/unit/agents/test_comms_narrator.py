"""Behavior tests for app.agents.core.background.comms_narrator.

Locks: the executor result is re-voiced through the comms graph as a
HumanMessage framed in the right internal tag (never a SystemMessage — the
regression the comment block warns about), the platform-delivery note is
prepended for workflow delivery, and every degradation path returns an empty
string instead of crashing the caller. Also the cancellation record appended
to the comms checkpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_executor_cancellation,
)
from app.agents.core.graph_manager import GraphUnavailableError
from app.agents.llm.lane import AgentRole
from app.agents.prompts.comms_prompts import (
    INTERACTIVE_DELIVERY_NOTE,
    PLATFORM_DELIVERY_NOTE,
)
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.general import NEW_MESSAGE_BREAKER

MODULE = "app.agents.core.background.comms_narrator"

USER: dict = {"user_id": "user-1", "email": "u@gaia.local"}
CONVERSATION_ID = "conv-1"
RESULT_TEXT = f"Downloaded the report.{NEW_MESSAGE_BREAKER}It has 3 pages."
CARD_NOTE = wrap_agent_payload(AgentTag.RETURNED_TO_FRONTEND, "a card is on screen")


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
        initial = silent.await_args.args[1]
        message = initial["messages"][0]
        assert isinstance(message, HumanMessage)
        assert message.name == "background_executor"
        assert message.content == (
            INTERACTIVE_DELIVERY_NOTE + wrap_agent_payload(AgentTag.EXECUTOR_RESULT, RESULT_TEXT)
        )
        config = silent.await_args.args[2]
        assert config["configurable"]["conversation_id"] == CONVERSATION_ID

    async def test_the_users_onboarding_data_reaches_build_agent_config(self) -> None:
        """``build_agent_config`` runs for real here (unmocked) — proves the
        (preferences, writing_style) pair extracted from ``user["onboarding"]``
        actually lands on the configurable this narration run carries, not just
        that the extraction call doesn't crash."""
        user_with_onboarding = {
            **USER,
            "onboarding": {
                "preferences": {"profession": "engineer"},
                "writing_style": {"summary": "terse"},
            },
        }
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result(
                RESULT_TEXT, "result", CONVERSATION_ID, user_with_onboarding
            )

        config = silent.await_args.args[2]
        assert config["configurable"]["user_preferences"] == {"profession": "engineer"}
        assert config["configurable"]["writing_style"] == {"summary": "terse"}

    async def test_error_type_uses_the_error_tag(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result("boom", "error", CONVERSATION_ID, USER)

        initial = silent.await_args.args[1]
        assert initial["messages"][0].content == (
            INTERACTIVE_DELIVERY_NOTE + wrap_agent_payload(AgentTag.EXECUTOR_ERROR, "boom")
        )

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
                returned_note=CARD_NOTE,
                workflow_id="wf-1",
            )

        content = silent.await_args.args[1]["messages"][0].content
        assert content.startswith(PLATFORM_DELIVERY_NOTE)
        assert f"<{AgentTag.EXECUTOR_RESULT}>" in content

    async def test_interactive_chat_prepends_the_returned_note(self) -> None:
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("revoiced", {}))
            ) as silent,
        ):
            await narrate_executor_result(
                RESULT_TEXT, "result", CONVERSATION_ID, USER, returned_note=CARD_NOTE
            )

        content = silent.await_args.args[1]["messages"][0].content
        # The card note comes first, then the bubble-split instruction, then the
        # result — comms reads "already shown" before it decides how to split.
        assert content == (
            CARD_NOTE
            + INTERACTIVE_DELIVERY_NOTE
            + wrap_agent_payload(AgentTag.EXECUTOR_RESULT, RESULT_TEXT)
        )

    async def test_parroted_internal_tags_are_stripped(self) -> None:
        """A weak model that echoes the whole framed block back keeps its words
        and loses the plumbing — both the open and the close tag."""
        parroted = wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "done")
        with (
            _patch_graph(_fake_comms_graph()),
            patch(
                f"{MODULE}.execute_graph_silent",
                AsyncMock(return_value=(parroted, {})),
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


class TestRecordExecutorCancellation:
    async def test_cancellation_record_is_appended_to_the_checkpoint(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_executor_cancellation(CONVERSATION_ID, "task-42", "send the email")

        graph.aupdate_state.assert_awaited_once()
        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        assert call.kwargs["as_node"] == "tools"
        messages = call.args[1]["messages"]
        assert len(messages) == 1
        # The whole record, not a fragment of it: this text is the only thing
        # that stops comms claiming a cancelled task finished, so every clause
        # of the denial is load-bearing and a test that matched one phrase let
        # the rest of the sentence be rewritten unnoticed.
        assert messages[0].content == wrap_agent_payload(
            AgentTag.EXECUTOR_CANCELLED,
            "The background task task-42 ('send the email') was cancelled by the user "
            "before it completed. It did NOT finish and will not deliver results — "
            "do not claim otherwise.",
        )

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


class TestNarrationResolvesItsOwnCommsLane:
    """Background narration is a top-level run with no parent to inherit from.

    It has to resolve its OWN lane, at the comms tier — the same model the user's
    interactive turns get, and the plan_type stamp the budget wall reads. Nothing
    asserted this, so mutating the role or the agent name survived the suite.
    """

    async def test_it_asks_for_a_comms_lane_on_the_comms_agent(self) -> None:
        graph = _fake_comms_graph()
        built = AsyncMock(return_value={"configurable": {}})
        with (
            _patch_graph(graph),
            patch(f"{MODULE}.build_agent_config", built),
            patch(f"{MODULE}.execute_graph_silent", AsyncMock(return_value=("narrated", {}))),
        ):
            await narrate_executor_result(
                result_text=RESULT_TEXT,
                msg_type="final",
                conversation_id=CONVERSATION_ID,
                user=USER,
            )

        kwargs = built.await_args.kwargs
        assert kwargs["role"] is AgentRole.COMMS
        assert kwargs["agent_name"] == "comms_agent"
        assert kwargs["conversation_id"] == CONVERSATION_ID
        # No base_configurable: inheriting one would carry a stale lane from
        # whatever run happened to be in flight.
        assert "base_configurable" not in kwargs
