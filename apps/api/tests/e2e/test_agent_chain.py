"""The composed chain: comms -> executor -> subagent, over ONE stream.

Only composition breaks these: one Redis subscription must see all three
tiers (call_executor's detached task, and every subagent it hands off to,
publish to the same stream_id); a tier's card must render before its own
result and a subagent's work must sit inside its start/end frames; a tool
call's subagent_id must survive two re-emission hops; tool_call_id is the
only join at any tier; and the comms turn is saved once, with the executor's
cards pushed onto that already-saved message while the executor still runs.

Everything from the comms model to Redis is real production code; the doubles
are listed on :func:run_chain, each one an external service, never a step in
the chain.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.store.memory import InMemoryStore
import pytest

from app.agents.core.background.redis_writer import STREAM_PUBLISH_TASK_NAME
from app.agents.core.graph_builder import build_graph as build_graph_module
from app.agents.core.graph_manager import GraphManager
from app.agents.core.nodes.follow_up_actions_node import FollowUpActions
from app.agents.core.subagents.provider_subagents import register_subagent_providers
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.memory import ReconcileOutcome
from app.core.lazy_loader import providers
from app.core.stream_manager import stream_manager
from app.db.redis import redis_cache
from app.memory.ingestion import RetainedMemory
from app.models.chat_models import ToolDataEntry
from app.models.memory_models import MemoryEntry
from app.models.message_models import MessageRequestWithHistory
from app.services.chat import stream as chat_stream
from app.utils import background_tasks
from tests.e2e._harness.graph_run import RecordingFakeModel, call, scripted_model
from tests.e2e._harness.transcript import UNKNOWN, Transcript

pytestmark = pytest.mark.e2e

USER: dict[str, Any] = {"user_id": "u-chain", "email": "chain@test.local", "name": "Test User"}

#: A builtin subagent (managed_by="internal": no OAuth/Composio needed) built by
#: the real SubAgentFactory. Auto-binds fetch_webpages, a real tool whose body
#: runs for real — only its HTTP fetch is doubled.
SUBAGENT_ID = "gaia_knowledge_guide"
SUBAGENT_AGENT = "gaia_knowledge_guide_agent"

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"


@pytest.fixture(autouse=True)
def _registry(real_tool_registry: Any) -> None:
    """Real tool categories — every tool_data frame resolves through them."""


@pytest.fixture(autouse=True)
async def fake_redis() -> Any:
    """Point the module singleton at an in-process Redis with real Streams.

    The outer half of test isolation; the inner half (deleting
    executor:busy:{conversation}, done in run_chain) matters because a leaked
    busy lock silently queues the next test's executor onto a different stream id.
    """
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis_cache.redis
    redis_cache.redis = client
    yield client
    redis_cache.redis = original
    await client.flushall()
    await client.connection_pool.disconnect()


class StreamingScriptedModel(RecordingFakeModel):
    """A scripted model that streams, because the real one does.

    LangGraph's messages mode attaches a streaming callback, so a provider like
    ChatOpenRouter emits AIMessageChunks even under ainvoke; RecordingFakeModel
    implements only _agenerate, so without this override LangGraph falls back to
    one whole AIMessage. That matters only in composition: _process_messages_payload
    (the executor/subagent driver) accepts AIMessageChunk alone, so a non-streaming
    double would collapse every answer to the "Task completed" fallback instead of
    the real text.
    """

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # Cursor advance lives in the base ``_generate``; calling it keeps one
        # script position whichever path a tier takes.
        message = super()._generate(messages, stop=stop, **kwargs).generations[0].message
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content,
                tool_calls=getattr(message, "tool_calls", []),
                id=message.id,
            )
        )
        if run_manager is not None:
            await run_manager.on_llm_new_token(chunk.text or "", chunk=chunk)
        yield chunk


def streaming_model(script: Sequence[Any]) -> StreamingScriptedModel:
    return StreamingScriptedModel(responses=scripted_model(script).responses)


@dataclass
class ChainRun:
    """One composed turn: what the client saw, and what was written down."""

    transcript: Transcript
    stream_id: str
    conversation_id: str
    #: Every ``save_conversation_async`` call — the comms turn's own persistence.
    saved: list[dict[str, Any]] = field(default_factory=list)
    #: Every ``append_message_tool_data`` call — the executor cards pushed onto
    #: the already-saved bot message after the executor finishes.
    attached: list[dict[str, Any]] = field(default_factory=list)
    #: ``(text, result_type)`` per executor delivery.
    delivered: list[tuple[str, str]] = field(default_factory=list)

    def attached_entries(self) -> list[dict[str, Any]]:
        return [entry for call_ in self.attached for entry in call_["entries"]]

    def attached_tool_names(self) -> list[str]:
        """Return the real tool name of every attached entry, envelope unwrapped."""
        names: list[str] = []
        for entry in self.attached_entries():
            data = entry.get("data")
            if entry.get("tool_name") == "tool_calls_data" and isinstance(data, dict):
                names.append(str(data.get("tool_name", "")))
            else:
                names.append(str(entry.get("tool_name", "")))
        return names

    def index_of_kind(self, kind: str) -> int:
        """Position of the first frame with this top-level key."""
        return self.transcript.kinds().index(kind)


def _tasks_named(*names: str) -> list[asyncio.Task[object]]:
    """Live background tasks carrying any of names.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def _drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs the background writer scheduled.

    make_redis_stream_writer is sync — it schedules each publish via
    spawn_background_task and returns, so a test reading the log after the turn
    must wait for them (by name, see _tasks_named) or read a truncated stream.
    """
    while pending := _tasks_named(STREAM_PUBLISH_TASK_NAME):
        await asyncio.gather(*pending, return_exceptions=True)


async def run_chain(
    prompt: str,
    *,
    comms: Sequence[Any],
    executor: Sequence[Any],
    subagent: Sequence[Any] | None = None,
    fetch_webpage: Any = None,
) -> ChainRun:
    """Drive one full turn through the real orchestrator and read the stream back.

    comms/executor/subagent are scripted_model scripts, one entry per model call. Doubled, all
    off the chain: tools store + checkpointer (exact_tool_names never searches), Mongo writes
    and reads (recorded; assertion targets), deliver_result, the memory engine and follow-up
    generator (as graph_run.comms_graph doubles them), and fetch_webpage's HTTP GET only.
    """
    conversation_id = str(uuid4())
    stream_id = str(uuid4())

    memory = MagicMock()
    memory.retain_single = AsyncMock(
        return_value=RetainedMemory(
            entry=MemoryEntry(id="mem-chain", content="test memory", category_path="general"),
            outcome=ReconcileOutcome.NEW,
        )
    )
    memory.recall = AsyncMock(return_value=MagicMock(entries=[], episodes=[]))

    run = ChainRun(
        transcript=Transcript.from_sse(""),
        stream_id=stream_id,
        conversation_id=conversation_id,
    )

    async def _save(**kwargs: Any) -> None:
        run.saved.append(kwargs)

    async def _attach(*_args: Any, **kwargs: Any) -> bool:
        run.attached.append(kwargs)
        return True

    async def _deliver(
        _run: Any,
        text: str,
        result_type: str,
        _note: str,
        *,
        tool_data: list[ToolDataEntry] | None,
    ) -> tuple[str, str]:
        run.delivered.append((text, result_type))
        return text, "executor-message-1"

    # The provider registry is process-wide with no reset between tests — without
    # a fresh loader per run, the first test's subagent graph (and its script)
    # would be reused by every later test in the session.
    if subagent is not None:
        register_subagent_providers([SUBAGENT_ID])

    patches = [
        patch.object(
            build_graph_module, "get_tools_store", AsyncMock(return_value=InMemoryStore())
        ),
        patch.object(build_graph_module, "get_checkpointer_manager", AsyncMock(return_value=None)),
        patch(
            f"{FOLLOW_UP_NODE}.ainvoke_structured",
            new=AsyncMock(return_value=FollowUpActions(actions=[])),
        ),
        patch(
            f"{FOLLOW_UP_NODE}.get_user_integration_capabilities",
            new=AsyncMock(return_value={"tool_names": []}),
        ),
        patch("app.agents.tools.memory_tools.memory_engine", memory),
        patch("app.agents.core.nodes.memory_node.memory_engine", memory),
        patch("app.services.chat.stream.save_conversation_async", new=_save),
        patch.object(chat_stream.conversation_repository, "append_message_tool_data", new=_attach),
        patch("app.agents.core.background.executor_runner.deliver_result", new=_deliver),
        patch(
            "app.services.files.FileService.list_conversation_files",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.core.background.executor_runner.has_bg_subagent_results",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.agents.core.background.executor_runner.list_parked_subagents_for_conversation",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.core.subagents.handoff_tools.list_parked_subagents_for_conversation",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_tools_store",
            new=AsyncMock(return_value=InMemoryStore()),
        ),
        patch(
            "app.agents.core.subagents.base_subagent.get_checkpointer_manager",
            new=AsyncMock(side_effect=RuntimeError("no postgres in tests")),
        ),
    ]
    if subagent is not None:
        patches.append(
            patch(
                "app.agents.core.subagents.provider_subagents.init_llm",
                return_value=streaming_model(subagent),
            )
        )
    if fetch_webpage is not None:
        patches.append(patch("app.agents.tools.webpage_tool.fetch_webpage", new=fetch_webpage))

    try:
        async with AsyncExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            comms_graph = await stack.enter_async_context(
                build_graph_module.build_comms_graph(
                    chat_llm=streaming_model(comms), in_memory_checkpointer=True
                )
            )
            executor_graph = await stack.enter_async_context(
                build_graph_module.build_executor_graph(
                    chat_llm=streaming_model(executor), in_memory_checkpointer=True
                )
            )
            graphs = {"comms_agent": comms_graph, "executor_agent": executor_graph}
            stack.enter_context(
                patch.object(
                    GraphManager,
                    "get_graph",
                    new=AsyncMock(side_effect=lambda name="default_graph": graphs[name]),
                )
            )

            await stream_manager.start_stream(
                stream_id=stream_id,
                conversation_id=conversation_id,
                user_id=str(USER["user_id"]),
            )
            await chat_stream.run_chat_stream_background(
                stream_id=stream_id,
                body=MessageRequestWithHistory(
                    message=prompt,
                    messages=[{"role": "user", "content": prompt}],
                    conversation_id=conversation_id,
                ),
                user=cast(Any, USER),
                conversation_id=conversation_id,
            )
            await _drain_publishes()
    finally:
        # A leaked busy lock survives 30 minutes and does not error — it queues
        # the NEXT test's executor onto its own stream id.
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
        if subagent is not None:
            await providers.areset(SUBAGENT_AGENT)

    frames = [chunk async for chunk in stream_manager.subscribe_stream(stream_id)]
    run.transcript = Transcript.from_sse("".join(frames))
    return run


# ---------------------------------------------------------------------------
# Scenario 2 — comms -> executor
# ---------------------------------------------------------------------------

#: Not in the executor's ``initial_tool_ids``, so reaching it exercises the real
#: ``retrieve_tools`` -> bind -> call hop; and pure, so its result is the tool's
#: real output rather than a doubled service's.
FLOWCHART_ARGS = {"description": "how a delegated turn flows", "direction": "LR"}


def executor_flowchart_script() -> list[Any]:
    return [
        call("retrieve_tools", {"exact_tool_names": ["create_flowchart"]}, call_id="tc_retrieve"),
        call("create_flowchart", FLOWCHART_ARGS, call_id="tc_flow"),
        "Drew the flowchart.",
    ]


class TestCommsToExecutor:
    async def test_the_executors_tool_call_lands_on_the_comms_stream(self) -> None:
        """Until now, prepare_executor_execution was stubbed at the comms tier — this never ran end to end."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        assert run.transcript.tool_names() == [
            "call_executor",
            "retrieve_tools",
            "create_flowchart",
        ]
        assert run.transcript.args("create_flowchart") == FLOWCHART_ARGS

    async def test_the_delegated_tools_real_output_joins_its_call_by_id(self) -> None:
        """Asserts on the tool's actual output, not just presence — a rejected/unbound/missing-user_id call also produces a joinable error string."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        result = run.transcript.result_for("create_flowchart")
        assert result is not None
        # Both arguments survive the whole trip and land inside the prompt the
        # tool composed — proof this is the tool's own output, not a placeholder.
        assert "description: how a delegated turn flows" in result
        assert "direction: LR" in result

    async def test_no_result_is_streamed_twice(self) -> None:
        """Two drivers (the executor's own runner and the still-open comms stream) can each emit the same ToolMessage — this is the only test that would catch it."""
        run = await run_chain(
            "draw me a flowchart",
            comms=comms_delegating_script(),
            executor=executor_flowchart_script(),
        )

        ids = [output.tool_call_id for output in run.transcript.outputs()]
        duplicated = sorted({tc_id for tc_id in ids if ids.count(tc_id) > 1})

        assert duplicated == [], f"streamed twice: {duplicated} (all outputs: {ids})"

    async def test_the_retrieval_hop_the_executor_takes_is_visible_to_the_user(self) -> None:
        """The bind step streams as its own card, from the same detached task the user is waiting on."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        assert run.transcript.args("retrieve_tools") == {"exact_tool_names": ["create_flowchart"]}
        assert (
            run.transcript.result_for("retrieve_tools")
            == "Bound 1 tools, call them directly:\n  - create_flowchart"
        )

    async def test_every_card_precedes_its_own_result_across_both_tiers(self) -> None:
        """One timeline for the user: the handoff card and each executor card land before their own result."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        calls = {c.name: c.index for c in run.transcript.tool_calls()}
        outputs = {o.tool_call_id: o.index for o in run.transcript.outputs()}
        assert calls["call_executor"] < calls["retrieve_tools"] < calls["create_flowchart"]
        assert calls["call_executor"] < outputs["tc_exec"]
        assert calls["retrieve_tools"] < outputs["tc_retrieve"]
        assert calls["create_flowchart"] < outputs["tc_flow"]

    async def test_comms_answers_immediately_instead_of_waiting_for_the_executor(self) -> None:
        """call_executor is fire-and-forget by design — if it ever blocked, the user would stare at nothing."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        assert run.transcript.result_for("call_executor").startswith("Task accepted (task_id:")
        assert run.transcript.final_text() == "On it."

    async def test_only_the_comms_tier_speaks_in_the_response_frames(self) -> None:
        """Both tiers share one graph driver; without this gate the executor's prose would interleave into the user's reply."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        assert run.transcript.final_text() == "On it."
        assert "Drew the flowchart." not in run.transcript.final_text()
        assert run.delivered == [("Drew the flowchart.", "final")]

    async def test_the_turn_is_saved_once_and_the_executor_cards_attach_afterwards(self) -> None:
        """The comms ack is saved before the executor wait so its position is right; saving or attaching twice would duplicate the turn or its cards."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        assert len(run.saved) == 1
        assert run.saved[0]["complete_message"] == "On it."
        saved_names = [
            entry["data"]["tool_name"] for entry in run.saved[0]["tool_data"]["tool_data"]
        ]
        assert saved_names == ["call_executor"]

        assert len(run.attached) == 1
        assert run.attached[0]["message_id"] == run.saved[0]["bot_message_id"]
        assert run.attached_tool_names() == ["retrieve_tools", "create_flowchart"]

    async def test_a_persisted_executor_card_carries_the_result_the_user_watched(self) -> None:
        """The attached entry is the reload's only copy of the executor's work — without its output the card renders as never finished."""
        run = await run_chain(
            "draw me a flowchart",
            comms=[
                call("call_executor", {"task": "draw a flowchart"}, call_id="tc_exec"),
                "On it.",
            ],
            executor=executor_flowchart_script(),
        )

        flowchart = next(
            entry
            for entry in run.attached_entries()
            if entry["data"]["tool_name"] == "create_flowchart"
        )
        assert flowchart["data"]["inputs"] == FLOWCHART_ARGS
        assert flowchart["data"]["output"] == run.transcript.result_for("create_flowchart")


# ---------------------------------------------------------------------------
# Scenario 3 — comms -> executor -> subagent
# ---------------------------------------------------------------------------

HANDOFF_ARGS = {"subagent_id": SUBAGENT_ID, "task": "what does GAIA's executor do?"}
PAGE_URL = "https://docs.gaia.test/executor"


def comms_delegating_script(task: str = "explain the executor") -> list[Any]:
    return [call("call_executor", {"task": task}, call_id="tc_exec"), "Looking that up."]


def executor_handoff_script() -> list[Any]:
    # Three entries, not two: the completion guard spends one nudge before
    # letting the plain-text stop through, and without repeating it the
    # cycling script would replay the handoff and run the subagent twice.
    return [
        call("handoff", HANDOFF_ARGS, call_id="tc_handoff"),
        "The executor runs delegated work.",
        "The executor runs delegated work.",
    ]


def subagent_fetch_script() -> list[Any]:
    return [
        call("fetch_webpages", {"urls": [PAGE_URL]}, call_id="tc_fetch"),
        "GAIA's executor runs delegated work in the background.",
    ]


def fetched_page(text: str = "The executor is GAIA's worker tier.") -> AsyncMock:
    return AsyncMock(return_value=text)


class TestExecutorToSubagent:
    async def test_all_three_tiers_land_on_one_stream(self) -> None:
        """Comms opened the stream; the executor and subagent publish onto it from a detached task two levels down."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        assert run.transcript.tool_names() == ["call_executor", "handoff", "fetch_webpages"]
        assert run.transcript.subagent_ids() != []

    async def test_the_subagents_tool_call_carries_its_subagent_id(self) -> None:
        """The frontend routes on subagent_id alone — untagged, the card would render at the turn's root instead of inside the subagent."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        row_id = run.transcript.subagent_ids()[0]
        assert run.transcript.tool_call("fetch_webpages").subagent_id == row_id
        assert run.transcript.tool_call("handoff").subagent_id is None

    async def test_the_subagents_result_joins_its_call_inside_the_group(self) -> None:
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page("The executor is GAIA's worker tier."),
        )

        row_id = run.transcript.subagent_ids()[0]
        result = run.transcript.result_for("fetch_webpages")
        assert result is not None
        assert "The executor is GAIA's worker tier." in result
        assert [
            o.subagent_id for o in run.transcript.outputs() if o.tool_call_id == "tc_fetch"
        ] == [row_id]

    async def test_the_subagents_work_is_bracketed_by_its_lifecycle_frames(self) -> None:
        """A tool card outside the subagent_start/subagent_end window has no row to render into."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        kinds = run.transcript.kinds()
        start = kinds.index("subagent_start")
        end = kinds.index("subagent_end")
        fetch = run.transcript.tool_call("fetch_webpages").index
        handoff = run.transcript.tool_call("handoff").index
        assert handoff < start < fetch < end

    async def test_the_subagents_answer_is_what_the_handoff_returns(self) -> None:
        """A subagent that ran a tool returns its own text, not the "re-issue the handoff" narration-only signal."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        assert (
            run.transcript.result_for("handoff")
            == "GAIA's executor runs delegated work in the background."
        )

    async def test_the_subagent_group_is_persisted_on_the_comms_message(self) -> None:
        """A reload has to show the subagent's work nested, not flattened next to the executor's own cards."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        group = next(
            entry for entry in run.attached_entries() if entry["tool_name"] == "subagent_group"
        )
        assert group["data"]["subagent_id"] == run.transcript.subagent_ids()[0]

        nested = {c["tool_name"]: c for c in group["data"]["tool_calls"]}

        assert "fetch_webpages" in nested, f"subagent's work not in the group: {list(nested)}"
        assert nested["fetch_webpages"]["tool_call_id"] == "tc_fetch"
        # The group carries the joined result, not just the call — a reload has
        # to render the card populated, not spinning.
        assert "The executor is GAIA's worker tier." in nested["fetch_webpages"]["output"]


# ---------------------------------------------------------------------------
# Scenario 4 — an integration tool at the end of the chain
# ---------------------------------------------------------------------------


class TestIntegrationToolThroughTheChain:
    """The executor cannot reach an integration tool directly; only a subagent can.

    gaia_knowledge_guide auto-binds fetch_webpages unconditionally, making it the
    one integration tool reachable in-process — the tool's real body runs, only
    its HTTP GET is doubled. The Composio-hosted toolkits (gmail, github, slack,
    todoist) are covered instead by test_integration_toolkits.py, which drives
    their real proxy/auth seams; building one here would need a fabricated tool
    list, so it wouldn't be the real tool.
    """

    async def test_the_tool_is_bound_without_a_retrieval_hop(self) -> None:
        """auto_bind_tools promises the tool is usable on the subagent's first call — a silent no-op would surface as a bind rejection."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        assert "retrieve_tools" not in run.transcript.tool_names()
        # Positively, not "no rejection appeared": `result_for` returns None when
        # nothing came back at all, and `not in (… or "")` reads that silence as
        # success — so the suppression of every tool_output would satisfy it.
        result = run.transcript.result_for("fetch_webpages")
        assert result is not None, "the bound tool produced no result at all"
        assert "The executor is GAIA's worker tier." in result

    async def test_the_tools_progress_events_reach_the_users_stream(self) -> None:
        """Progress events cross the subagent driver, the executor driver and Redis — three hops that only exist in composition."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page(),
        )

        progress = run.transcript.of_kind("progress")
        assert any(PAGE_URL in str(step) for step in progress)
        assert "Fetching Complete!" in progress

    async def test_the_native_card_payload_reaches_the_wire_unwrapped(self) -> None:
        """Pins a known defect (same class as the plan's image_data gap, §6b): no envelope means the client renders nothing."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=fetched_page("The executor is GAIA's worker tier."),
        )

        cards = [
            frame
            for frame in run.transcript.of_kind(UNKNOWN)
            if isinstance(frame, dict) and "webpage_data" in frame
        ]
        assert len(cards) == 1
        assert "The executor is GAIA's worker tier." in cards[0]["webpage_data"]
        assert cards[0]["fetched_urls"] == [PAGE_URL]
        # No envelope, so nothing in the turn's tool_data can carry it.
        assert not any(
            isinstance(entry, dict) and entry.get("tool_name") == "webpage_data"
            for entry in run.transcript.of_kind("tool_data")
        )

    async def test_a_failed_fetch_still_completes_the_turn(self) -> None:
        """The tool swallows a per-URL failure as progress; the chain must not take the whole turn down with it."""
        run = await run_chain(
            "explain the executor",
            comms=comms_delegating_script(),
            executor=executor_handoff_script(),
            subagent=subagent_fetch_script(),
            fetch_webpage=AsyncMock(side_effect=RuntimeError("host unreachable")),
        )

        assert any("host unreachable" in str(step) for step in run.transcript.of_kind("progress"))
        assert run.transcript.is_done
        assert run.transcript.final_text() == "Looking that up."
        assert len(run.saved) == 1
