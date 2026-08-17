"""A finished spawn is recovered, not re-run, when a later sibling pauses the node.

The scenario the spawn-thread lifecycle exists for: one AI message carries two
``spawn_subagent`` calls. The tool node runs them sequentially — spawn A finishes
(side effect done), spawn B pauses on an approval ``interrupt()``. LangGraph
re-runs the WHOLE node on resume, so spawn A's tool function is entered a second
time. Its checkpoint thread — deliberately retained instead of deleted at finish —
is what tells that replay A already ran, via ``recover_from_checkpoint``.

Real: ``SubagentMiddleware._run_spawn``/``_drive``, the compiled spawn graph
(``_build_spawn_graph`` via ``get_spawn_graph``), LangGraph interrupt/resume on a
checkpointer, and ``recover_from_checkpoint``. Replaced, and only these: the LLM
(message-driven fake, so it behaves identically on a replay), the dynamic-context
message (external retrieval I/O), and the checkpointer manager (``InMemorySaver``).

The pause is a tool calling ``interrupt()`` before its side effect — the exact
shape of the HIL gate's pause (which has its own coverage in
``tests/unit/services/hil/``); the claim under test here is the node-replay
recovery, not the gate's policy.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.core.subagents import spawn_agent
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.middleware.factory import create_subagent_middleware
from app.agents.middleware.subagent import SubagentMiddleware
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.general import FINISH_TASK_NAME
from app.constants.hil import HIL_RESUME_CONFIG_KEY, LANGGRAPH_INTERRUPT_KEY

TASK_A = "ALPHA: record the meeting note"
TASK_B = "BETA: publish the status update"


class TaskDrivenFakeLLM:
    """Chooses its tool from the Task line it is shown, never from a call counter.

    Message-driven on purpose: a node replay shows the model the same messages,
    so it must produce the same output — a sequence-driven fake would desync.
    """

    def __init__(self) -> None:
        self.invocations: list[str] = []

    def with_config(self, **_kwargs: Any) -> "TaskDrivenFakeLLM":
        return self

    def bind_tools(self, _tools: Any, **_kwargs: Any) -> "TaskDrivenFakeLLM":
        return self

    def with_retry(self, **_kwargs: Any) -> "TaskDrivenFakeLLM":
        return self

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        text = " ".join(str(getattr(m, "content", "")) for m in messages)
        task = "alpha" if "ALPHA" in text else "beta"
        self.invocations.append(task)
        answered = any(getattr(m, "type", "") == "tool" for m in messages)
        if answered:
            return AIMessage(content=f"{task} done")
        if task == "alpha":
            return AIMessage(
                content="",
                tool_calls=[{"id": "in-a-1", "name": "record_note", "args": {"text": "minutes"}}],
            )
        return AIMessage(
            content="",
            tool_calls=[{"id": "in-b-1", "name": "publish_update", "args": {"text": "shipped"}}],
        )


@pytest.fixture
def effects() -> dict[str, int]:
    return {"record_note": 0, "publish_update": 0}


@pytest.fixture
def spawn_tools(effects: dict[str, int]) -> dict[str, Any]:
    @tool
    async def record_note(text: str) -> str:
        """Record a note (spawn A's side effect — must happen exactly once)."""
        effects["record_note"] += 1
        return f"noted: {text}"

    @tool
    async def publish_update(text: str) -> str:
        """Publish an update, pausing for approval first (the HIL gate's shape)."""
        from langgraph.types import interrupt

        decision = interrupt({"type": "hil_approval", "tool_name": "publish_update"})
        effects["publish_update"] += 1
        return f"published after {decision.get('status')}"

    return {"record_note": record_note, "publish_update": publish_update}


async def test_finished_spawn_is_recovered_not_rerun_when_a_sibling_pauses(
    effects: dict[str, int], spawn_tools: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    saver = InMemorySaver()
    llm = TaskDrivenFakeLLM()
    monkeypatch.setattr(spawn_agent, "_graph_cache", {})

    runtime = ToolRuntimeConfig(
        initial_tool_names=["record_note", "publish_update", FINISH_TASK_NAME],
        enable_retrieve_tools=False,
        include_subagents_in_retrieve=False,
    )

    # Kept so assertions read spawn threads through the spawn graph's own state
    # schema (DeltaChannel messages) — exactly how recover_from_checkpoint reads
    # them; the parent graph's plain MessagesState lens would see them as empty.
    spawn_graph_holder: dict[str, Any] = {}

    async def provider(**kwargs: Any) -> Any:
        graph = await get_spawn_graph(**kwargs)
        graph.checkpointer = saver
        spawn_graph_holder["graph"] = graph
        return graph

    middleware = SubagentMiddleware(
        llm=llm,
        tool_registry=spawn_tools,
        tool_space="general",
        tool_runtime_config=runtime,
        # The REAL middleware stack, not [] — its tool-invocation wrap chain is what
        # re-raises GraphInterrupt as control flow; a bare tool node converts it into
        # an error ToolMessage and the pause never happens (verified by running both).
        spawn_middleware_factory=lambda space: create_subagent_middleware(
            enable_subagent=False, subagent_tool_space=space
        ),
    )
    middleware.set_spawn_graph_provider(provider)

    async def tool_node(_state: MessagesState, config: RunnableConfig) -> dict:
        # Two spawn calls from one AI message, run sequentially — the production
        # tool node's loop. On resume LangGraph re-runs this whole function.
        text_a = await middleware._run_spawn(
            task=TASK_A, context="", config=config, tool_call_id="tc-a", inherited_tool_names=[]
        )
        text_b = await middleware._run_spawn(
            task=TASK_B, context="", config=config, tool_call_id="tc-b", inherited_tool_names=[]
        )
        return {"messages": [AIMessage(content=f"{text_a} | {text_b}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    parent = builder.compile(checkpointer=saver)

    conv = "sibling-replay-conv"

    def config_for(resuming: bool) -> RunnableConfig:
        base: dict[str, Any] = {
            "thread_id": f"executor_{conv}",
            "conversation_id": conv,
            "user_id": "user-1",
            "email": "sibling@test.local",
            "user_name": "Sibling",
            "stream_id": "stream-sibling-1",
        }
        if resuming:
            # The production contract: the executor's resume re-dispatch sets this
            # (executor_runner), and it is what arms the checkpoint probe.
            base[HIL_RESUME_CONFIG_KEY] = True
        return {"configurable": base}

    # External-I/O seams only: context retrieval, tools store, checkpointer
    # source, and the tool_data category lookup (a lazy provider backed by
    # ChromaDB in production).
    with (
        patch(
            "app.agents.core.subagents.subagent_runner.assemble_context",
            AsyncMock(
                return_value=AssembledContext(
                    stable=SystemMessage(
                        content="ctx", additional_kwargs={"dynamic_context": True}
                    ),
                    volatile=None,
                )
            ),
        ),
        patch(
            "app.agents.core.subagents.spawn_agent.get_tools_store", AsyncMock(return_value=None)
        ),
        patch(
            "app.agents.core.subagents.spawn_agent.get_checkpointer_manager",
            AsyncMock(return_value=SimpleNamespace(get_checkpointer=lambda: saver)),
        ),
        patch(
            "app.utils.agent_utils.get_tool_registry",
            AsyncMock(return_value=SimpleNamespace(get_category_of_tool=lambda _name: "general")),
        ),
    ):
        # First pass: A finishes, B pauses, the parent parks.
        first_events = [
            ev
            async for ev in parent.astream(
                {"messages": [HumanMessage(content="go")]},
                config=config_for(resuming=False),
                stream_mode=["updates", "custom"],
            )
        ]
        paused = [
            payload[LANGGRAPH_INTERRUPT_KEY]
            for mode, payload in first_events
            if mode == "updates" and LANGGRAPH_INTERRUPT_KEY in payload
        ]
        assert paused, "spawn B's approval interrupt must park the parent"
        assert effects["record_note"] == 1, "spawn A's side effect ran on the first pass"
        assert effects["publish_update"] == 0, "spawn B must not act before approval"

        spawn_graph = spawn_graph_holder["graph"]
        snapshot_a = await spawn_graph.aget_state(
            {"configurable": {"thread_id": f"spawn_{conv}_tc-a"}}
        )
        assert not snapshot_a.next, "spawn A's thread is finished"
        assert snapshot_a.values.get("messages"), "…and retained, so the replay can read it"
        alpha_calls_before_resume = llm.invocations.count("alpha")

        # Resume: the node replays from the top. A recovers; only B runs.
        final_state = await parent.ainvoke(
            Command(resume={"status": "approved"}), config=config_for(resuming=True)
        )

    assert effects["record_note"] == 1, "the replay must recover spawn A, not re-run it"
    assert effects["publish_update"] == 1, "spawn B ran exactly once after approval"
    assert llm.invocations.count("alpha") == alpha_calls_before_resume, (
        "spawn A's graph was never driven again on the replay"
    )

    # "alpha done" can only have come from A's checkpoint: the live streaming path
    # yields the "Task completed" fallback for this non-streaming fake (B's half of
    # the text shows exactly that), so recovery is what produced A's real answer.
    final_text = str(final_state["messages"][-1].content)
    assert "alpha done" in final_text, "A's answer came back from its checkpoint"

    snapshot_b = await spawn_graph.aget_state({"configurable": {"thread_id": f"spawn_{conv}_tc-b"}})
    assert not snapshot_b.next, "spawn B's thread finished after the approval"
    assert str(snapshot_b.values["messages"][-1].content) == "beta done"
