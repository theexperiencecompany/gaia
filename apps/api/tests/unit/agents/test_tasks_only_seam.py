"""The TASKS_ONLY flag seam: which comms graph, tools and prompt a turn gets, and that flag off is the current path."""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.agent import AgentRunOptions, _core_agent_logic
from app.agents.core.background.executor_capture import (
    await_executor_done,
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.session import mark_task_handed_off
from app.agents.core.graph_builder.build_graph import comms_tools
from app.agents.prompts.comms_prompts import TASKS_ONLY_ADDENDUM
from app.agents.templates.agent_template import get_comms_static_prompt
from app.constants.tasks import FACT_FRESHNESS_TEXT, TASKS_ONLY_COMMS_GRAPH_NAME
from app.helpers.message_helpers import create_system_message
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.chat.stream import _executor_delegation

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
EXECUTOR_TOOLS = {"call_executor", "cancel_executor", "read_work_record"}
TASK_TOOLS = {"start_task", "message_task", "cancel_task", "find_tasks", "read_task"}


class TestToolRegistration:
    def test_flag_off_comms_has_the_executor_tools_and_no_task_tool(self) -> None:
        names = set(comms_tools())

        assert names >= EXECUTOR_TOOLS
        assert not names & TASK_TOOLS

    def test_tasks_only_comms_has_the_task_tools_and_no_direct_executor(self) -> None:
        names = set(comms_tools(tasks_only=True))

        assert names >= TASK_TOOLS
        assert not names & EXECUTOR_TOOLS

    def test_everything_else_comms_can_do_is_the_same_under_the_flag(self) -> None:
        assert set(comms_tools()) - EXECUTOR_TOOLS == set(comms_tools(tasks_only=True)) - TASK_TOOLS


class TestPrompt:
    def test_flag_off_the_prompt_is_the_current_one_byte_for_byte(self) -> None:
        for source in (None, "web", "whatsapp"):
            message = create_system_message(source=source)

            assert message.content == get_comms_static_prompt(source)
            assert "start_task" not in message.content

    def test_tasks_only_appends_the_task_rules_to_the_same_prompt(self) -> None:
        message = create_system_message(source="web", tasks_only=True)

        assert message.content == get_comms_static_prompt("web") + TASKS_ONLY_ADDENDUM
        assert "start_task" in message.content

    def test_the_addendum_names_every_task_tool_and_the_freshness_windows(self) -> None:
        assert all(name in TASKS_ONLY_ADDENDUM for name in TASK_TOOLS)
        assert FACT_FRESHNESS_TEXT in TASKS_ONLY_ADDENDUM


def _user() -> AuthenticatedUser:
    return AuthenticatedUser.model_validate(
        {"user_id": USER_ID, "email": "test@example.com", "name": "Test User"}
    )


def _request() -> MessageRequestWithHistory:
    return MessageRequestWithHistory.model_validate(
        {"message": "hi", "messages": [{"role": "user", "content": "hi"}]}
    )


class TestGraphSelection:
    @pytest.fixture
    def turn(self):
        """Double the turn's collaborators; yield (get_graph, construct, flag)."""
        with (
            patch("app.agents.core.agent.read_presence", AsyncMock(return_value=None)),
            patch("app.agents.core.agent.conversation_repository.set_run_context", AsyncMock()),
            patch(
                "app.agents.core.agent.construct_langchain_messages",
                AsyncMock(return_value=[HumanMessage(content="hi")]),
            ) as construct,
            patch(
                "app.agents.core.agent.GraphManager.get_graph", AsyncMock(return_value=MagicMock())
            ) as get_graph,
            patch("app.agents.core.agent.build_initial_state", return_value={}),
            patch(
                "app.agents.core.agent.build_agent_config",
                AsyncMock(return_value={"configurable": {"thread_id": "c1"}}),
            ),
            patch("app.agents.core.agent.log"),
            patch("app.agents.core.agent.is_tasks_only_enabled", AsyncMock()) as flag,
        ):
            yield get_graph, construct, flag

    async def test_flag_on_the_turn_runs_the_tasks_only_graph_and_prompt(self, turn) -> None:
        get_graph, construct, flag = turn
        flag.return_value = True

        await _core_agent_logic(_request(), "c1", _user())

        get_graph.assert_awaited_once_with(TASKS_ONLY_COMMS_GRAPH_NAME)
        assert construct.call_args.kwargs["scope"].tasks_only is True
        flag.assert_awaited_once_with(USER_ID)

    async def test_flag_off_the_turn_runs_the_current_graph_and_prompt(self, turn) -> None:
        get_graph, construct, flag = turn
        flag.return_value = False

        await _core_agent_logic(_request(), "c1", _user())

        get_graph.assert_awaited_once_with("comms_agent")
        assert construct.call_args.kwargs["scope"].tasks_only is False

    async def test_a_background_run_never_leaves_the_current_path_even_when_the_flag_is_on(
        self, turn
    ) -> None:
        get_graph, construct, flag = turn
        flag.return_value = True

        await _core_agent_logic(
            _request(),
            "c1",
            _user(),
            AgentRunOptions(trigger_context={"execution_mode": "background"}),
        )

        get_graph.assert_awaited_once_with("comms_agent")
        assert construct.call_args.kwargs["scope"].tasks_only is False
        flag.assert_not_awaited()


class TestHandOff:
    @pytest.fixture
    def stream_id(self):
        stream_id = "tasks-only-seam-stream"
        register_executor_capture(stream_id)
        yield stream_id
        teardown_executor_capture(stream_id)

    def test_a_turn_with_no_work_is_not_a_delegation(self, stream_id: str) -> None:
        assert _executor_delegation(stream_id) == (False, False)

    async def test_a_started_task_makes_a_silent_turn_an_accepted_hand_off_with_nothing_to_wait_for(
        self, stream_id: str
    ) -> None:
        mark_task_handed_off(stream_id)

        assert _executor_delegation(stream_id) == (True, False)
        assert await await_executor_done(stream_id, timeout=0.1) is True
