"""E2E tests: workflow execution, plus the agent-graph lifecycle it runs on.

Sibling: ``tests/integration/test_workflow_execution.py`` covers the workflow
service layer in isolation (mocked I/O); this file drives the real compiled
agent graphs end to end.

WHAT THIS TESTS (REAL GAIA CODE):
- ``execute_workflow_by_id`` / ``execute_workflow_as_chat`` from
  ``app.workers.tasks.workflow_tasks`` — the real entry point a workflow fire
  goes through — together with ``app.services.workflow.execution_service``:
  a step that fails partway through a multi-step workflow must surface as a
  ``failed`` execution record naming the failing step plus a user notification,
  never as a silent success.
- ``build_comms_graph`` / ``build_executor_graph`` from
  ``app.agents.core.graph_builder.build_graph`` compile with the REAL middleware
  stack (``create_comms_middleware`` / ``create_executor_middleware``) and that
  stack is reachable at runtime: its hooks run and its tools are bound.
- The GAIA ``State`` schema from ``app.override.langgraph_bigtool.utils``
  contains the ``todos`` channel and ``selected_tool_ids``.
- ``MemorySaver`` checkpointing accumulates state across multiple graph turns.
- Graph thread isolation: separate thread_ids produce independent state.

Mock surfaces (I/O edges only):
- LLM: FakeMessagesListChatModel / a scripted stand-in for the agent turn
- store: InMemoryStore (no ChromaDB), checkpointer: MemorySaver (no PostgreSQL)
- Mongo repositories, Redis-backed scheduler, notification delivery
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core import agent as agent_module
from app.agents.core.graph_builder.build_graph import build_comms_graph, build_executor_graph
from app.agents.middleware.accounting import LLMAccountingMiddleware
from app.agents.tools.todo_tools import TODO_TOOL_NAMES
from app.api.v1.middleware import tiered_rate_limiter
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.agent_models import SilentRunResult
from app.models.workflow_execution_models import (
    WorkflowExecutionDocument,
    WorkflowExecutionUpdate,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowStep,
)
from app.override.langgraph_bigtool.utils import _replace_todos, dedupe_str_list
from app.services.workflow.scheduler import WorkflowScheduler
from app.workers.tasks import workflow_tasks
from app.workers.tasks.workflow_tasks import execute_workflow_by_id
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel


@pytest.mark.e2e
class TestWorkflowExecution:
    """E2E tests for GAIA graph lifecycle and state schema correctness."""

    async def test_todos_channel_uses_replace_reducer(self):
        """The 'todos' channel must use last-write-wins (replace) semantics.

        _replace_todos is the reducer for the State.todos channel. When two
        successive updates arrive, the second list must completely replace the
        first — not merge or append to it.

        If _replace_todos is removed from utils.py or its semantics change,
        this test will fail.
        """
        first_todos = ["Buy milk", "Call dentist"]
        second_todos = ["Submit report"]

        result = _replace_todos(first_todos, second_todos)

        assert result == second_todos, (
            "_replace_todos must return the right-hand (newest) list, "
            "not the left-hand one or a merge of both."
        )
        assert "Buy milk" not in result, "Previous todos must be fully replaced, not merged."

    def test_selected_tool_ids_channel_deduplicates(self):
        """dedupe_str_list must remove duplicate tool IDs while preserving order.

        selected_tool_ids accumulates IDs across tool-retrieval turns. When the
        same ID appears multiple times, only the first occurrence must be kept.

        If dedupe_str_list is removed from utils.py, this test fails.
        """
        ids_with_duplicates = ["tool_a", "tool_b", "tool_a", "tool_c", "tool_b"]

        result = dedupe_str_list(ids_with_duplicates)

        assert result == ["tool_a", "tool_b", "tool_c"], (
            "dedupe_str_list must remove duplicates while preserving first-seen order."
        )
        assert len(result) == 3

    async def test_compiled_graph_returns_gaia_state_on_invoke(
        self, thread_config, in_memory_store, memory_saver
    ):
        """A compiled GAIA graph must return state with GAIA-specific channels.

        When ainvoke() returns, the result dict must contain 'todos' and
        'selected_tool_ids' — channels that exist only in the GAIA State schema,
        not in generic LangGraph MessagesState.
        """
        fake_llm = BindableToolsFakeModel(responses=[AIMessage(content="Workflow complete.")])

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Run the workflow")]},
            config=thread_config,
        )

        assert "messages" in result
        assert "todos" in result, (
            "Graph result must include 'todos' (GAIA State channel). "
            "This confirms the graph uses GAIA State, not generic MessagesState."
        )
        assert "selected_tool_ids" in result, (
            "Graph result must include 'selected_tool_ids' (GAIA bigtool State channel)."
        )

    async def test_checkpointing_accumulates_messages_across_turns(
        self, in_memory_store, memory_saver
    ):
        """MemorySaver checkpointing must accumulate messages across multiple invocations.

        This tests GAIA's State schema + MemorySaver integration: the same
        thread_id must produce accumulated state (messages from turn 1 remain
        visible in turn 2) — the same pattern used by build_comms_graph in
        production. It is NOT a test of MemorySaver in isolation; it proves
        that the GAIA State channels (with their reducers) wire correctly with
        LangGraph's checkpointing mechanism.
        """
        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(content="Response to first message."),
                AIMessage(content="Response to second message."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry={},
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        thread_id = str(uuid4())
        user_id = str(uuid4())
        config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

        # First invocation
        await graph.ainvoke(
            {"messages": [HumanMessage(content="First message")]},
            config=config,
        )

        # Second invocation on the SAME thread
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Second message")]},
            config=config,
        )

        state_snapshot = await graph.aget_state(config)
        accumulated = state_snapshot.values["messages"]

        # Should have: HumanMessage1, AIMessage1, HumanMessage2, AIMessage2
        assert len(accumulated) == 4, (
            f"Expected 4 accumulated messages after 2 turns, got {len(accumulated)}. "
            "MemorySaver checkpointing must accumulate state across turns."
        )

        # Assert on specific message content to prove both turns were persisted
        contents = [m.content for m in accumulated]
        assert "First message" in contents, (
            "Turn-1 HumanMessage must be present in the accumulated checkpoint."
        )
        assert "Second message" in contents, (
            "Turn-2 HumanMessage must be present in the accumulated checkpoint."
        )
        assert "Response to first message." in contents, (
            "Turn-1 AIMessage must be present in the accumulated checkpoint."
        )
        assert "Response to second message." in contents, (
            "Turn-2 AIMessage must be present in the accumulated checkpoint."
        )

    async def test_different_thread_ids_have_independent_state(self, in_memory_store):
        """Separate thread_ids must not share state (thread isolation).

        This mirrors how the production comms agent handles concurrent users:
        each conversation thread is completely isolated.

        Each thread receives a unique sentinel phrase in its human message.
        After both graphs run, we assert:
        - Thread A's state contains only thread-A's sentinel (not thread B's).
        - Thread B's state contains only thread-B's sentinel (not thread A's).
        """
        checkpointer = MemorySaver()

        # Unique sentinel phrases that cannot appear in each other's thread
        sentinel_a = f"SENTINEL-ALPHA-{uuid4().hex}"
        sentinel_b = f"SENTINEL-BETA-{uuid4().hex}"

        fake_llm_a = BindableToolsFakeModel(
            responses=[AIMessage(content=f"Acknowledged: {sentinel_a}")]
        )
        fake_llm_b = BindableToolsFakeModel(
            responses=[AIMessage(content=f"Acknowledged: {sentinel_b}")]
        )

        graph_a = build_gaia_test_graph(
            fake_llm=fake_llm_a,
            tool_registry={},
            checkpointer=checkpointer,
            store=in_memory_store,
        )
        graph_b = build_gaia_test_graph(
            fake_llm=fake_llm_b,
            tool_registry={},
            checkpointer=checkpointer,
            store=in_memory_store,
        )

        config_a = {"configurable": {"thread_id": "thread-alpha", "user_id": str(uuid4())}}
        config_b = {"configurable": {"thread_id": "thread-beta", "user_id": str(uuid4())}}

        await graph_a.ainvoke(
            {"messages": [HumanMessage(content=f"Message for alpha: {sentinel_a}")]},
            config=config_a,
        )
        await graph_b.ainvoke(
            {"messages": [HumanMessage(content=f"Message for beta: {sentinel_b}")]},
            config=config_b,
        )

        state_a = await graph_a.aget_state(config_a)
        state_b = await graph_b.aget_state(config_b)

        all_content_a = " ".join(m.content for m in state_a.values["messages"])
        all_content_b = " ".join(m.content for m in state_b.values["messages"])

        assert sentinel_a in all_content_a, (
            f"Thread A must contain its own sentinel phrase. Got: {all_content_a!r}"
        )
        assert sentinel_b not in all_content_a, (
            f"Thread A must NOT contain thread B's sentinel. Got: {all_content_a!r}"
        )
        assert sentinel_b in all_content_b, (
            f"Thread B must contain its own sentinel phrase. Got: {all_content_b!r}"
        )
        assert sentinel_a not in all_content_b, (
            f"Thread B must NOT contain thread A's sentinel. Got: {all_content_b!r}"
        )

    async def test_comms_graph_runs_its_real_middleware_stack(self):
        """build_comms_graph must wire the REAL comms middleware, and it must run.

        The middleware stack is core orchestration, not an I/O edge, so it is
        deliberately NOT mocked here: ``create_comms_middleware`` builds the real
        stack and the graph is invoked for real. A spy that delegates to the real
        ``LLMAccountingMiddleware.aafter_model`` proves the stack is actually
        reached during the turn rather than merely constructed — replacing the
        middleware list with ``[]`` (or dropping the MiddlewareExecutor wiring in
        ``create_agent``) makes this test fail.
        """

        fake_llm = BindableToolsFakeModel(responses=[AIMessage(content="Comms agent response.")])

        async def _noop_hook(state, config, store):  # NOSONAR — LangGraph hook interface
            return state

        agents_that_ran_middleware: list[str] = []
        real_aafter_model = LLMAccountingMiddleware.aafter_model

        async def _spy_aafter_model(self, *args, **kwargs):
            agents_that_ran_middleware.append(self.agent_name)
            return await real_aafter_model(self, *args, **kwargs)

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new_callable=AsyncMock,
                return_value=InMemoryStore(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.follow_up_actions_node",
                new=_noop_hook,
            ),
            patch("app.agents.core.graph_builder.build_graph.memory_node", new=_noop_hook),
            patch.object(LLMAccountingMiddleware, "aafter_model", _spy_aafter_model),
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Hello from comms graph test")]},
                    config={
                        "configurable": {
                            "thread_id": str(uuid4()),
                            "user_id": str(uuid4()),
                        }
                    },
                )

        assert "messages" in result, "Comms graph result must contain 'messages' key"
        assert agents_that_ran_middleware == ["comms_agent"], (
            "The real comms middleware stack must run exactly once for a one-turn "
            f"comms invocation. Middleware runs observed: {agents_that_ran_middleware!r}"
        )

    async def test_comms_graph_binds_its_memory_tools(self):
        """The comms agent's memory tools must be bound, not rejected as unbound.

        ``search_memory`` is one of the three tools the comms agent is allowed to
        call. If it were dropped from the registry / initial_tool_ids, the real
        ``reject_unbound_tools`` node would answer the call with an "is not bound"
        error instead of running it — which is what this asserts against.
        """

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_memory", "args": {"query": "birthday"}, "id": "call-1"}
                    ],
                ),
                AIMessage(content="Nothing found."),
            ]
        )

        async def _noop_hook(state, config, store):  # NOSONAR — LangGraph hook interface
            return state

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new_callable=AsyncMock,
                return_value=InMemoryStore(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.follow_up_actions_node",
                new=_noop_hook,
            ),
            patch("app.agents.core.graph_builder.build_graph.memory_node", new=_noop_hook),
        ):
            async with build_comms_graph(chat_llm=fake_llm, in_memory_checkpointer=True) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="What did I say about birthdays?")]},
                    config={
                        "configurable": {
                            "thread_id": str(uuid4()),
                            "user_id": str(uuid4()),
                        }
                    },
                )

        tool_messages = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and m.name == "search_memory"
        ]
        assert tool_messages, "search_memory must produce a ToolMessage — the comms graph ran it"
        assert "is not bound" not in tool_messages[0].text, (
            "search_memory must be bound on the comms agent, but reject_unbound_tools "
            f"rejected it: {tool_messages[0].text!r}"
        )

    async def test_executor_graph_binds_the_real_subagent_middleware_tool(self):
        """build_executor_graph must wire the REAL executor middleware stack.

        ``spawn_subagent`` exists only because ``create_executor_middleware``
        contributes a ``SubagentMiddleware`` whose tools ``create_agent`` binds.
        Mocking the middleware factory to ``[]`` (as this test used to) hides that
        wiring completely: the model's ``spawn_subagent`` call then falls through
        to ``reject_unbound_tools``. Asserting the call is NOT rejected proves the
        real middleware stack is present and its tool is reachable.
        """
        import ast
        import inspect

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "spawn_subagent",
                            "args": {"task": "summarize the inbox"},
                            "id": "call-1",
                        }
                    ],
                ),
                AIMessage(content="Executor agent response."),
            ]
        )

        def _make_stub(name: str):
            async def _stub(query: str = "") -> str:
                return f"stub:{name}"

            _stub.__name__ = name
            _stub.__doc__ = f"Stub for {name}."
            return lc_tool(_stub)

        # Dynamically read initial_tool_ids from the real source so the mock
        # registry always provides stubs for every tool the graph expects.
        src = inspect.getsource(build_executor_graph)
        injected_by_graph = {"handoff"} | TODO_TOOL_NAMES
        idx = src.find("initial_tool_ids=")
        if idx != -1:
            bracket_start = src.index("[", idx)
            bracket_end = src.index("]", bracket_start) + 1
            raw_ids: list[str] = ast.literal_eval(src[bracket_start:bracket_end])
        else:
            raw_ids = []
        tool_dict = {tid: _make_stub(tid) for tid in raw_ids if tid not in injected_by_graph}

        mock_registry = MagicMock()
        mock_registry.get_tool_dict.return_value = tool_dict

        async def _fake_retrieve_tools(store, config, query=None, exact_tool_names=None):
            """Minimal stub with proper signature for StructuredTool.from_function."""
            return {"tools_to_bind": [], "response": []}

        with (
            patch(
                "app.agents.core.graph_builder.build_graph.get_tool_registry",
                new_callable=AsyncMock,
                return_value=mock_registry,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_tools_store",
                new_callable=AsyncMock,
                return_value=InMemoryStore(),
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_retrieve_tools_function",
                return_value=_fake_retrieve_tools,
            ),
            patch(
                "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
        ):
            async with build_executor_graph(
                chat_llm=fake_llm, in_memory_checkpointer=True
            ) as graph:
                result = await graph.ainvoke(
                    {"messages": [HumanMessage(content="Hello from executor graph test")]},
                    config={
                        "configurable": {
                            "thread_id": str(uuid4()),
                            "user_id": str(uuid4()),
                        }
                    },
                )

        assert "messages" in result, "Executor graph result must contain 'messages' key"
        spawn_results = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and m.name == "spawn_subagent"
        ]
        assert spawn_results, (
            "spawn_subagent must produce a ToolMessage — the executor graph must route "
            "the call to the SubagentMiddleware tool."
        )
        assert "is not bound" not in spawn_results[0].text, (
            "spawn_subagent must be bound via the real SubagentMiddleware, but "
            f"reject_unbound_tools rejected it: {spawn_results[0].text!r}"
        )


class _InMemoryExecutionRecords:
    """Stand-in for the Mongo side of ``workflow_executions_repository``.

    Only the three base CRUD primitives are replaced, so the repository's own
    ``complete()`` (status/duration/error-message assembly) and both execution
    service functions still run for real.
    """

    def __init__(self) -> None:
        self.records: dict[str, WorkflowExecutionDocument] = {}

    async def create(self, document: WorkflowExecutionDocument) -> WorkflowExecutionDocument:
        self.records[document.execution_id] = document
        return document

    async def get(self, execution_id: str, **_: object) -> WorkflowExecutionDocument | None:
        return self.records.get(execution_id)

    async def update(
        self, execution_id: str, update: WorkflowExecutionUpdate
    ) -> WorkflowExecutionDocument | None:
        existing = self.records.get(execution_id)
        if existing is None:
            return None
        # Re-validate rather than model_copy: Mongo stores the $set dicts and the
        # repository validates them back into the document model on read, so a
        # copy that skips validation would hand tests shapes production never sees.
        updated = WorkflowExecutionDocument.model_validate(
            {**existing.model_dump(), **update.model_dump(exclude_unset=True)}
        )
        self.records[execution_id] = updated
        return updated

    def only(self) -> WorkflowExecutionDocument:
        assert len(self.records) == 1, f"Expected exactly one execution, got {self.records!r}"
        return next(iter(self.records.values()))


def _make_multi_step_workflow(user_id: str) -> Workflow:
    return Workflow(
        user_id=user_id,
        title="Morning briefing",
        description="Summarize overnight mail and post it to Slack.",
        prompt="Summarize overnight mail and post it to Slack.",
        trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
        steps=[
            WorkflowStep(id="s1", title="Read overnight email", category="gmail", description="a"),
            WorkflowStep(
                id="s2", title="Summarize the thread", category="general", description="b"
            ),
            WorkflowStep(id="s3", title="Post to Slack", category="slack", description="c"),
        ],
    )


@pytest.mark.e2e
class TestWorkflowExecutionFailurePropagation:
    """E2E tests for the real workflow-execution path.

    Drives ``execute_workflow_by_id`` — the function an actual workflow fire
    (manual "run now", a schedule, or an integration trigger) lands on — through
    ``execute_workflow_as_chat`` and ``app.services.workflow.execution_service``.
    Only I/O edges are replaced: the Redis-backed scheduler, the Mongo side of the
    execution/workflow repositories, notification delivery, and the agent turn
    that stands in for the LLM.
    """

    @pytest.fixture
    def workflow_execution_env(self, monkeypatch):
        """Patch every I/O edge of the execution path and expose the observable ones."""

        # These workflows have no playbook, so every run here takes the agentic
        # path. Stubbed explicitly rather than left to the mocked Mongo client so
        # the tests exercise the real "no playbook" branch instead of the
        # lookup-failure fallback, which would hide a broken agentic path.
        monkeypatch.setattr(playbook_repository, "get_for_workflow", AsyncMock(return_value=None))

        records = _InMemoryExecutionRecords()
        monkeypatch.setattr(workflow_executions_repository, "create", records.create)
        monkeypatch.setattr(workflow_executions_repository, "get", records.get)
        monkeypatch.setattr(workflow_executions_repository, "update", records.update)

        recorded_stats: list[bool] = []

        async def _record_execution(_workflow_id, _user_id, *, successful):
            recorded_stats.append(successful)
            return True

        monkeypatch.setattr(workflow_repository, "record_execution", _record_execution)

        notifications: list[object] = []

        async def _create_notification(request):
            notifications.append(request)

        monkeypatch.setattr(
            workflow_tasks.notification_service, "create_notification", _create_notification
        )

        monkeypatch.setattr(WorkflowScheduler, "initialize", AsyncMock())
        monkeypatch.setattr(WorkflowScheduler, "close", AsyncMock())
        monkeypatch.setattr(
            workflow_tasks,
            "get_or_create_workflow_conversation",
            AsyncMock(return_value="conv-workflow-1"),
        )
        monkeypatch.setattr(
            workflow_tasks, "add_workflow_execution_messages", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            workflow_tasks, "get_user_by_id", AsyncMock(return_value={"timezone": "UTC"})
        )
        # The checkpoint reset is Postgres; its own behaviour is proven in
        # tests/unit/services/workflow/test_thread_reset.py.
        monkeypatch.setattr(workflow_tasks, "reset_workflow_threads", AsyncMock(return_value=0))
        monkeypatch.setattr(
            tiered_rate_limiter.tiered_limiter, "check_and_increment", AsyncMock(return_value={})
        )

        return {
            "records": records,
            "recorded_stats": recorded_stats,
            "notifications": notifications,
        }

    @staticmethod
    def _install_stepwise_agent(monkeypatch, failing_step_title: str | None) -> list[str]:
        """Replace the agent turn with one that walks the workflow's steps in order.

        Returns the list the stand-in appends each completed step title to, so a
        test can prove the run stopped *partway* rather than after every step.
        """

        completed: list[str] = []

        async def _run_steps(request, conversation_id, user, options=None):
            tool_data: list[dict[str, object]] = []
            for step in request.selectedWorkflow.steps:
                if step["title"] == failing_step_title:
                    raise RuntimeError(
                        f"Step '{step['title']}' failed: Gmail API returned 503 Service Unavailable"
                    )
                completed.append(step["title"])
                tool_data.append(
                    {
                        "tool_name": "tool_calls_data",
                        "data": {
                            "tool_name": step["title"],
                            "inputs": {"step_id": step["id"]},
                            "output": "ok",
                        },
                    }
                )
            return SilentRunResult(message="", tool_data={"tool_data": tool_data})

        monkeypatch.setattr(agent_module, "call_agent_silent", _run_steps)
        return completed

    async def test_step_failure_records_a_failed_execution_naming_the_step(
        self, monkeypatch, workflow_execution_env
    ):
        """A step that fails partway through must surface as a failed execution.

        The user-visible outcome of a broken workflow run is its execution record
        and the failure notification. Both must say the run failed and carry the
        failing step's identity — a swallowed step error (``execute_workflow_as_chat``
        returning instead of re-raising) would silently record 'success'.
        """

        workflow = _make_multi_step_workflow(user_id=str(uuid4()))
        completed = self._install_stepwise_agent(
            monkeypatch, failing_step_title="Summarize the thread"
        )

        monkeypatch.setattr(WorkflowScheduler, "get_task", AsyncMock(return_value=workflow))

        result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        assert completed == ["Read overnight email"], (
            "Execution must stop at the failing step — steps after it must not run. "
            f"Completed: {completed!r}"
        )

        execution = workflow_execution_env["records"].only()
        assert execution.status == "failed", (
            f"A failed step must record status 'failed', got {execution.status!r}. "
            "A step failure that reaches the completion record as 'success' means the "
            "error was swallowed somewhere on the way up."
        )
        assert execution.error_message is not None
        assert "Summarize the thread" in execution.error_message, (
            "The execution record must name the step that failed, otherwise the user "
            f"cannot tell what broke. Got: {execution.error_message!r}"
        )
        assert "503" in execution.error_message, (
            f"The underlying cause must survive into the record. Got: {execution.error_message!r}"
        )
        assert execution.summary is None, "A failed run must not carry a success summary"
        assert execution.completed_at is not None and execution.duration_seconds is not None

        assert workflow_execution_env["recorded_stats"] == [False], (
            "The run must be counted as an unsuccessful execution exactly once, got "
            f"{workflow_execution_env['recorded_stats']!r}"
        )

        notifications = workflow_execution_env["notifications"]
        assert len(notifications) == 1, f"Expected one failure notification, got {notifications!r}"
        assert notifications[0].user_id == workflow.user_id
        assert workflow.title in notifications[0].content.title
        assert notifications[0].metadata["workflow_id"] == workflow.id

        assert "Error executing workflow" in result, (
            f"The task's return value must report the failure, got {result!r}"
        )

    async def test_all_steps_succeeding_records_a_successful_execution(
        self, monkeypatch, workflow_execution_env
    ):
        """Control for the failure test: an uneventful run must record success.

        Without this, a mutation that hard-codes 'failed' everywhere would still
        leave the failure test green.
        """

        workflow = _make_multi_step_workflow(user_id=str(uuid4()))
        completed = self._install_stepwise_agent(monkeypatch, failing_step_title=None)

        monkeypatch.setattr(WorkflowScheduler, "get_task", AsyncMock(return_value=workflow))

        result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        assert completed == [
            "Read overnight email",
            "Summarize the thread",
            "Post to Slack",
        ], f"Every step must run when none fails. Completed: {completed!r}"

        execution = workflow_execution_env["records"].only()
        assert execution.status == "success"
        assert execution.error_message is None
        assert execution.conversation_id == "conv-workflow-1", (
            "A successful run must link the conversation holding its messages"
        )
        assert [call.tool_name for call in execution.trace] == completed, (
            "A successful run must record what it did — the next run reads this "
            "instead of replaying the conversation's checkpoints"
        )
        assert execution.trace[0].args == {"step_id": "s1"}
        assert workflow_execution_env["recorded_stats"] == [True]
        assert workflow_execution_env["notifications"] == [], (
            "A successful run must not raise a failure notification"
        )
        assert "executed successfully" in result

    async def test_execution_record_is_completed_even_when_notification_delivery_fails(
        self, monkeypatch, workflow_execution_env
    ):
        """Notification delivery is best-effort; it must not lose the failure record.

        If the notification service is down, the user still needs the execution
        history to show the run failed.
        """

        workflow = _make_multi_step_workflow(user_id=str(uuid4()))
        self._install_stepwise_agent(monkeypatch, failing_step_title="Post to Slack")

        monkeypatch.setattr(WorkflowScheduler, "get_task", AsyncMock(return_value=workflow))
        monkeypatch.setattr(
            workflow_tasks.notification_service,
            "create_notification",
            AsyncMock(side_effect=RuntimeError("notification backend unreachable")),
        )

        result = await execute_workflow_by_id({}, workflow.id, {"trigger_type": "manual"})

        execution = workflow_execution_env["records"].only()
        assert execution.status == "failed"
        assert "Post to Slack" in (execution.error_message or "")
        assert workflow_execution_env["recorded_stats"] == [False]
        assert "Error executing workflow" in result

    async def test_missing_workflow_creates_no_execution_record(
        self, monkeypatch, workflow_execution_env
    ):
        """A fire for a deleted workflow must not leave a dangling 'running' record."""

        monkeypatch.setattr(WorkflowScheduler, "get_task", AsyncMock(return_value=None))

        result = await execute_workflow_by_id({}, "wf_deleted", {"trigger_type": "manual"})

        assert result == "Workflow wf_deleted not found"
        assert workflow_execution_env["records"].records == {}, (
            "No execution record may be created for a workflow that no longer exists"
        )
        assert workflow_execution_env["recorded_stats"] == []
        assert workflow_execution_env["notifications"] == []
