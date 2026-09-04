"""Service tests: a gated tool inside ``spawn_subagent``, end to end on live infra.

A gated call inside a spawn used to fail closed — refused with the unpausable
denial and the user never asked. These drive the real production path against real
Postgres (so the interrupt, the checkpoint and the node replay are genuine), real
MongoDB (approval records, preferences) and real Redis.

Real: the compiled spawn graph (``spawn_agent._build_spawn_graph``), the real
``SubagentMiddleware._run_spawn``/``_drive``, the real middleware stack, and the
real HIL gate. Substituted, and only these: the LLM (deterministic, message-driven
so a replay behaves identically) and the gated tool's side effect (a counter,
because "it happened exactly once" is the claim under test).

The sibling-replay case here is the live counterpart of
``tests/integration/agents/test_spawn_sibling_replay.py``: that one proves the
recovery against an in-memory saver with a hand-made pause, this one proves it
with the real gate and a real Postgres checkpoint.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool as make_tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command
import pytest

from app.agents.core.subagents import spawn_agent
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.middleware.factory import SubagentStackOptions, create_subagent_middleware
from app.agents.middleware.subagent import SubagentMiddleware, SubagentMiddlewareConfig
from app.agents.tools.core.registry import init_tool_registry
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.general import FINISH_TASK_NAME
from app.constants.hil import HIL_RESUME_CONFIG_KEY, LANGGRAPH_INTERRUPT_KEY
from app.models.hil_models import HILApprovalStatus, HILPreferences
from app.services.hil.approvals_store import list_pending_for_conversation, mark_decided
from tests.helpers import PassthroughFakeLLM

pytestmark = pytest.mark.e2e

SLACK_TASK = "post the release note to #eng"
NOTE_TASK = "ALPHA: record the meeting note"
# A SECOND gated task: also send_slack, but the spawn emits a DISTINCT inner
# tool_call_id, so its approval_id differs from SLACK_TASK's. Two gated siblings
# with distinct approval_ids is what the decision-routing test needs.
SLACK_TASK_2 = "BETA: post the incident note to #eng"


class TaskDrivenStubLLM(PassthroughFakeLLM):
    """Picks its tool from the Task line it is shown, never from a call counter.

    Message-driven on purpose: a node replay shows the model the same messages, so
    it must produce the same output — a sequence-driven stub would desync. Every
    spawn in a process shares the cached graph and therefore this one instance,
    which is why it dispatches on the task text.
    """

    def __init__(self) -> None:
        self.seen: list[Any] = []
        self.alpha_invocations = 0

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        self.seen = list(messages)
        text = " ".join(str(getattr(m, "content", "")) for m in self.seen)
        answered = any(getattr(m, "type", "") == "tool" for m in self.seen)
        if "ALPHA" in text:
            self.alpha_invocations += 1
            if answered:
                return AIMessage(content="alpha done")
            return AIMessage(
                content="",
                tool_calls=[{"id": "tc-note-1", "name": "record_note", "args": {"text": "m"}}],
            )
        if "BETA" in text:
            if answered:
                return AIMessage(content="Done with the incident request.")
            return AIMessage(
                content="",
                tool_calls=[{"id": "tc-slack-2", "name": "send_slack", "args": {"to": "#eng"}}],
            )
        if answered:
            return AIMessage(content="Done with the slack request.")
        return AIMessage(
            content="",
            tool_calls=[{"id": "tc-slack-1", "name": "send_slack", "args": {"to": "#eng"}}],
        )


@pytest.fixture
def side_effects() -> dict[str, int]:
    return {"send_slack": 0, "record_note": 0}


@pytest.fixture
def spawn_tools(side_effects: dict[str, int]) -> dict[str, Any]:
    @make_tool
    async def send_slack(to: str) -> str:
        """Post a message to a Slack channel."""
        side_effects["send_slack"] += 1
        return f"posted to {to}"

    @make_tool
    async def record_note(text: str) -> str:
        """Record a note (the ungated sibling's side effect)."""
        side_effects["record_note"] += 1
        return f"noted: {text}"

    return {"send_slack": send_slack, "record_note": record_note}


@pytest.fixture
async def gated_user(mongo_db):
    """A user with HIL on: ``send_slack`` always asks, ``record_note`` never does.

    Explicit per-tool overrides so gating is decided without the classifier's LLM
    call. Written through ``mongo_db`` — the database the repository layer is
    patched at, and therefore the one the gate reads.
    """
    user_oid = ObjectId()
    await mongo_db["users"].insert_one(
        {
            "_id": user_oid,
            "email": f"spawn-hil-{user_oid}@example.com",
            "hil_preferences": HILPreferences(
                mode="always_ask",
                tool_overrides={"send_slack": True, "record_note": False},
            ).model_dump(),
        }
    )

    yield str(user_oid)

    await mongo_db["users"].delete_one({"_id": user_oid})


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> TaskDrivenStubLLM:
    # The spawn graph is cached per (model, tool space, runtime signature); clearing
    # it keeps one test's compiled graph — and its bound stub — out of the next.
    monkeypatch.setattr(spawn_agent, "_graph_cache", {})
    return TaskDrivenStubLLM()


def interrupts(events: list) -> list:
    return [
        payload[LANGGRAPH_INTERRUPT_KEY]
        for mode, payload in events
        if mode == "updates" and isinstance(payload, dict) and LANGGRAPH_INTERRUPT_KEY in payload
    ]


def approval_id_of(events: list) -> str:
    """The approval_id carried by the single interrupt in ``events``."""
    raw = interrupts(events)[0]
    items = raw if isinstance(raw, list | tuple) else (raw,)
    value = getattr(items[0], "value", items[0])
    return str(value["approval_id"])


class SpawnDriver:
    """Runs spawns inside a parent tool node, the way the executor's node does."""

    def __init__(
        self,
        saver: AsyncPostgresSaver,
        llm: TaskDrivenStubLLM,
        tools: dict[str, Any],
        user_id: str,
    ) -> None:
        self._saver = saver
        self._llm = llm
        self._tools = tools
        self._user_id = user_id
        self._runtime = ToolRuntimeConfig(
            initial_tool_names=["send_slack", "record_note", FINISH_TASK_NAME],
            enable_retrieve_tools=False,
            include_subagents_in_retrieve=False,
        )

    async def _provider(self, **kwargs: Any) -> Any:
        # The real spawn graph; only its checkpointer is pinned to this connection
        # so the test can inspect the thread afterwards.
        graph = await get_spawn_graph(**kwargs)
        graph.checkpointer = self._saver
        return graph

    def _middleware(self) -> SubagentMiddleware:
        middleware = SubagentMiddleware(
            SubagentMiddlewareConfig(
                llm=self._llm,
                tool_registry=self._tools,
                tool_space="general",
                tool_runtime_config=self._runtime,
                # The REAL middleware stack: its tool-invocation wrap chain is what
                # re-raises GraphInterrupt as control flow. A bare tool node turns the
                # pause into an error ToolMessage and no approval ever happens.
                spawn_middleware_factory=lambda space: create_subagent_middleware(
                    subagent=SubagentStackOptions(enabled=False, tool_space=space)
                ),
            )
        )
        middleware.set_spawn_graph_provider(self._provider)
        return middleware

    async def _settle(self, conv: str, decision: dict[str, Any]) -> None:
        """File the decision on its record, the way the resolution layer does.

        The gate reads its verdict from the record and treats the resume payload as
        nothing but a wake-up, so a decision that was never filed leaves the call
        pending and the replay refuses it. An explicit ``approval_id`` settles that one
        approval and leaves a gated sibling still pending, which is how a turn holding
        two approvals can decide them differently.
        """
        approval_id = decision.get("approval_id")
        targets = (
            [approval_id]
            if approval_id
            else [record.approval_id for record in await list_pending_for_conversation(conv)]
        )
        for target in targets:
            await mark_decided(
                target,
                HILApprovalStatus(decision["status"]),
                feedback=decision.get("feedback"),
                scope=decision.get("scope", "once"),
                decided_by=self._user_id,
            )

    async def run(self, conv: str, tasks: list[tuple[str, str]], resume: Any | None = None) -> list:
        """Drive ``tasks`` as [(task, tool_call_id), ...] in ONE parent node."""
        middleware = self._middleware()
        if resume is not None:
            await self._settle(conv, resume)

        async def tool_node(_state: MessagesState, config: RunnableConfig) -> dict:
            texts = [
                await middleware._run_spawn(
                    task=task,
                    context="",
                    config=config,
                    tool_call_id=tool_call_id,
                    inherited_tool_names=[],
                )
                for task, tool_call_id in tasks
            ]
            return {"messages": [AIMessage(content=" | ".join(texts))]}

        builder = StateGraph(MessagesState)
        builder.add_node("tools", tool_node)
        builder.add_edge(START, "tools")
        builder.add_edge("tools", END)
        parent = builder.compile(checkpointer=self._saver)

        configurable: dict[str, Any] = {
            "thread_id": f"executor_{conv}",
            "conversation_id": conv,
            "user_id": self._user_id,
            "stream_id": f"spawn-stream-{conv}",
            "user_messages": [SLACK_TASK],
        }
        if resume is not None:
            # The production contract: the executor's resume re-dispatch sets this,
            # and it is what arms the finished/parked checkpoint probe.
            configurable[HIL_RESUME_CONFIG_KEY] = True

        payload = (
            Command(resume=resume)
            if resume is not None
            else {"messages": [HumanMessage(content="go")]}
        )
        return [
            event
            async for event in parent.astream(
                payload, config={"configurable": configurable}, stream_mode=["updates", "custom"]
            )
        ]


@pytest.fixture
async def driver(gated_user, stub_llm, spawn_tools, real_redis, postgres_url: str):
    # Register ONLY the provider the gate resolves through (has_pausing_sibling ->
    # get_tool_registry). register_lazy_providers() would also register the whole
    # app, and init_langfuse there blocks ~120s on a network reachability check
    # despite that function documenting itself as I/O-free.
    init_tool_registry()
    async with AsyncPostgresSaver.from_conn_string(postgres_url) as saver:
        await saver.setup()
        # The approval card's integration label needs the ChromaDB tool registry and
        # is cosmetic; the tools store is a lazy provider this process never
        # registers, and these graphs run with retrieve_tools disabled.
        with (
            patch(
                "app.services.hil.gate._integration_name_for", new=AsyncMock(return_value="Slack")
            ),
            patch(
                "app.agents.core.subagents.spawn_agent.get_tools_store",
                AsyncMock(return_value=None),
            ),
        ):
            yield SpawnDriver(saver, stub_llm, spawn_tools, gated_user), saver


class TestGatedToolInsideASpawn:
    async def test_it_pauses_the_parent_and_runs_once_when_approved(
        self, driver, side_effects: dict[str, int], hil_approvals_collection
    ) -> None:
        spawn_driver, saver = driver
        conv = f"spawn-hil-{ObjectId()}"
        spawn_thread = f"spawn_{conv}_parent-tc-1"

        events = await spawn_driver.run(conv, [(SLACK_TASK, "parent-tc-1")])

        paused = interrupts(events)
        assert paused, "a gated tool inside a spawn must pause the parent, not be refused"
        raw = paused[0]
        items = raw if isinstance(raw, list | tuple) else (raw,)
        value = getattr(items[0], "value", items[0])
        assert value.get("tool_name") == "send_slack", (
            f"the approval names the gated tool, got {value.get('tool_name')}"
        )
        assert side_effects["send_slack"] == 0, "nothing may run before approval"
        assert await saver.aget_tuple({"configurable": {"thread_id": spawn_thread}}) is not None, (
            "the parked spawn is checkpointed so a decision can resume it"
        )

        events = await spawn_driver.run(
            conv, [(SLACK_TASK, "parent-tc-1")], resume={"status": "approved", "scope": "once"}
        )

        assert side_effects["send_slack"] == 1, "the approved action runs exactly once"
        assert not interrupts(events), "the parent finishes without re-pausing"
        # The spawn no longer disposes of its own thread: a later sibling can still
        # pause, replaying this node, and the checkpoint is what tells that replay
        # the spawn already finished. The nightly sweep reclaims it once stale.
        assert await saver.aget_tuple({"configurable": {"thread_id": spawn_thread}}) is not None, (
            "the finished spawn's thread is retained for a sibling's replay"
        )

    async def test_a_denial_means_the_action_never_runs(
        self, driver, stub_llm: TaskDrivenStubLLM, side_effects: dict[str, int]
    ) -> None:
        spawn_driver, _saver = driver
        conv = f"spawn-hil-{ObjectId()}"

        await spawn_driver.run(conv, [(SLACK_TASK, "parent-tc-1")])
        events = await spawn_driver.run(
            conv, [(SLACK_TASK, "parent-tc-1")], resume={"status": "denied", "scope": "once"}
        )

        assert side_effects["send_slack"] == 0, "a denied action never runs"
        assert not interrupts(events), "the parent finishes rather than re-pausing"
        refusals = [
            m
            for m in stub_llm.seen
            if getattr(m, "type", "") == "tool" and getattr(m, "name", "") == "send_slack"
        ]
        assert refusals and any(
            phrase in str(m.content).lower()
            for m in refusals
            for phrase in ("did not run", "declined", "denied", "not approved")
        ), "the model inside the spawn must be told its call was declined"


class TestSiblingReplay:
    async def test_a_finished_sibling_spawn_is_recovered_not_rerun(
        self, driver, stub_llm: TaskDrivenStubLLM, side_effects: dict[str, int]
    ) -> None:
        """Two spawns in one AI message: A finishes, B pauses, the node replays.

        A's retained checkpoint is what stops its side effect happening twice.
        """
        spawn_driver, saver = driver
        conv = f"spawn-hil-{ObjectId()}"
        tasks = [(NOTE_TASK, "tc-sib-a"), (SLACK_TASK, "tc-sib-b")]

        events = await spawn_driver.run(conv, tasks)

        assert interrupts(events), "sibling B's gated call parks the parent"
        assert side_effects["record_note"] == 1, "sibling A ran on the first pass"
        assert (
            await saver.aget_tuple({"configurable": {"thread_id": f"spawn_{conv}_tc-sib-a"}})
            is not None
        ), "sibling A's finished thread is retained"
        alpha_calls_before_resume = stub_llm.alpha_invocations

        events = await spawn_driver.run(conv, tasks, resume={"status": "approved", "scope": "once"})

        assert side_effects["record_note"] == 1, (
            "the replay must recover sibling A from its checkpoint, not re-run it"
        )
        assert stub_llm.alpha_invocations == alpha_calls_before_resume, (
            "sibling A's graph was never driven again on the replay"
        )
        assert side_effects["send_slack"] == 1, "sibling B ran exactly once after approval"
        assert not interrupts(events), "the parent finishes without re-pausing"


class TestConcurrentGatedSiblings:
    async def test_each_sibling_gets_its_own_decision_not_the_first(
        self, driver, side_effects: dict[str, int]
    ) -> None:
        """Two GATED siblings in one parent turn, decided DIFFERENTLY.

        The node serializes them, so each bubbles up to the parent's ``_drive`` as its
        own pause — but on recovery the executor replays its interrupt() resume list
        positionally from zero, so the second gate would otherwise be handed the FIRST
        gate's decision. Approve A, deny B: the fix routes each decision to its own gate
        by ``approval_id``, so send_slack runs exactly once (A), never for the denied B.
        Without the fix B replays A's approval and send_slack runs twice.
        """
        spawn_driver, _saver = driver
        conv = f"spawn-hil-{ObjectId()}"
        tasks = [(SLACK_TASK, "tc-sib-a"), (SLACK_TASK_2, "tc-sib-b")]

        # Pass 1: sibling A's gate parks the parent (B not reached yet).
        events = await spawn_driver.run(conv, tasks)
        approval_a = approval_id_of(events)
        assert side_effects["send_slack"] == 0, "nothing runs before a decision"

        # Approve A: A runs, then B's gate parks.
        events = await spawn_driver.run(
            conv, tasks, resume={"status": "approved", "scope": "once", "approval_id": approval_a}
        )
        assert side_effects["send_slack"] == 1, "the approved sibling A ran exactly once"
        approval_b = approval_id_of(events)
        assert approval_b != approval_a, "the two siblings are distinct approvals"

        # Deny B: the replayed approval-A decision must NOT reach B's gate.
        events = await spawn_driver.run(
            conv, tasks, resume={"status": "denied", "scope": "once", "approval_id": approval_b}
        )
        assert side_effects["send_slack"] == 1, (
            "the denied sibling B never ran — its gate got B's denial, not A's approval"
        )
        assert not interrupts(events), "both siblings are resolved; the parent finishes"
