"""The composed chain: comms -> executor -> subagent, over ONE stream.

Every tier already has a suite of its own. What none of them can see is what
only composition breaks, and that is the whole subject of this file:

* **One stream.** ``call_executor`` returns "Task accepted" in milliseconds and
  spawns a *detached* task. That task publishes straight to Redis on the
  ``stream_id`` the comms turn opened (``background/redis_writer.py``), and so
  does every subagent it hands off to. A single subscription must therefore see
  all three tiers. Nothing before this file subscribed.
* **Renderable order.** The user watches one timeline. A tier's card must
  appear before its own result, and a subagent's work must sit between its
  ``subagent_start`` and ``subagent_end``.
* **Routing survives two hops.** A subagent's tool call is emitted by the
  subagent driver, re-emitted through the executor's custom stream, then
  published. ``subagent_id`` has to survive both.
* **The join survives too.** ``tool_call_id`` is the only thing tying a result
  to its card at any tier.
* **Persistence.** The comms turn is saved once, and the executor's cards are
  pushed onto that already-saved message afterwards — the executor is still
  running when the save happens.

Everything between the comms model and Redis is production code: the real
``run_chat_stream_background``, the real ``call_executor``, the real background
runner, the real ``handoff``, the real subagent factory, the real tools. The
doubles are listed on :func:`run_chain`, and each one is an external service,
never a step in the chain.
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

#: A builtin subagent — ``managed_by="internal"``, so resolving it needs no
#: OAuth record and no Composio call, and its graph is built by the real
#: ``SubAgentFactory``. It auto-binds ``fetch_webpages``, which is a real tool
#: with a real body; only the HTTP fetch inside it is doubled.
SUBAGENT_ID = "gaia_knowledge_guide"
SUBAGENT_AGENT = "gaia_knowledge_guide_agent"

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"


@pytest.fixture(autouse=True)
def _registry(real_tool_registry: Any) -> None:
    """Real tool categories — every ``tool_data`` frame resolves through them."""


@pytest.fixture(autouse=True)
async def fake_redis() -> Any:
    """Point the module singleton at an in-process Redis with real Streams.

    A fresh instance per test is the outer half of the isolation rule; the inner
    half (deleting ``executor:busy:{conversation}``) is in :func:`run_chain`,
    because a leaked busy lock does not error — it silently queues the next
    executor onto a *different* stream id, and the test then asserts an empty
    stream and passes for the wrong reason.
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

    The agent node calls ``ainvoke``, and LangChain streams under it whenever a
    streaming callback handler is attached — LangGraph's ``messages`` mode
    installs exactly such a handler, so a provider like ``ChatOpenRouter``
    delivers ``AIMessageChunk``s even on an ``ainvoke``.

    ``RecordingFakeModel`` implements only ``_agenerate``, so LangGraph falls
    back to emitting one whole ``AIMessage`` instead. That matters *only* in
    composition: ``execute_graph_streaming`` (comms) accepts both shapes, but
    ``_process_messages_payload`` — the driver the executor and every subagent
    run through — accepts ``AIMessageChunk`` alone. With a non-streaming double
    every executor and subagent answer collapses to the "Task completed"
    fallback, which would make an assertion on a subagent's returned text an
    assertion about the double rather than about GAIA.
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
        """The real tool name of every attached entry, envelope unwrapped."""
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
    """Live background tasks carrying any of ``names``.

    Filtering by name rather than draining the whole keep-alive set: that set
    also holds work which outlives a single turn, so awaiting all of it would
    hang here forever instead of failing a test.
    """
    wanted = set(names)
    return [t for t in background_tasks._background_tasks if t.get_name() in wanted]


async def _drain_publishes() -> None:
    """Wait out the fire-and-forget XADDs the background writer scheduled.

    ``make_redis_stream_writer`` is a *sync* callable — it schedules each publish
    through ``spawn_background_task`` and returns. A live subscriber sees those
    frames whenever they land, but a test that reads the log after the turn must
    wait for them, or it reads a truncated stream and the assertion is about
    timing rather than behaviour. Waits on exactly the publish
    tasks, by name — see :func:`_tasks_named`.
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

    ``comms`` / ``executor`` / ``subagent`` are scripts in the
    :func:`~tests.e2e._harness.graph_run.scripted_model` shape — one entry per
    model call at that tier.

    The doubles, and why each one is not part of the chain:

    * ``get_tools_store`` / ``get_checkpointer_manager`` — ChromaDB and Postgres.
      Binding by ``exact_tool_names`` never searches the store, so the retrieval
      hop stays real and embedding-free.
    * ``save_conversation_async`` / ``append_message_tool_data`` — Mongo. Both
      are recorded, and both are assertion targets.
    * ``deliver_result`` — the executor's *separate* answer message: a second LLM
      narration, a Mongo write and a WebSocket push. It is downstream of the
      stream, not on it. Recorded so a test can still see what was delivered.
    * ``FileService.list_conversation_files`` and the parked/background-subagent
      lookups — Mongo reads on the executor's prep and finalize paths.
    * the memory engine and the follow-up generator — the comms graph's two
      external end-graph edges, doubled exactly as ``graph_run.comms_graph``
      doubles them.
    * ``fetch_webpage`` — the HTTP GET inside ``fetch_webpages``. The tool's own
      body still runs.
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

    # A fresh loader per run, from the real registration path: the provider
    # registry is process-wide with no reset between tests, so without this the
    # FIRST test's subagent graph — and its script — would be reused by every
    # later test in the session.
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
        """Scenario 2, end to end. Until now ``prepare_executor_execution`` was
        stubbed at the comms tier, so the delegated tool never ran and never had
        to reach the user's stream."""
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
        """The join is the only thing tying a result to its card, and it has to
        survive the detached task and the Redis round trip.

        Asserted on the tool's actual content, not on "a result arrived": a
        rejected tool, an unbound tool and a missing ``user_id`` all produce a
        perfectly joinable *error string*.
        """
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
        """One ``tool_output`` per call, at the executor tier as well.

        Two drivers can see the same ``ToolMessage``: the executor's own
        (``subagent_runner``) and the comms driver (``execute_graph_streaming``),
        whose stream is still open while the detached executor task runs. Both
        emit, and the client renders the card twice.

        Every other assertion in this file is blind to it, which is why this one
        exists: ``Transcript.result_for()`` returns the FIRST output matching a
        ``tool_call_id`` and discards the rest, so a duplicate is invisible to
        any content check. Compare the whole list, not a lookup.

        Which result doubles is a race — it is whichever lands while the comms
        stream is still open — so this asserts over every id rather than naming
        one.
        """
        run = await run_chain(
            "draw me a flowchart",
            comms=comms_delegating_script(),
            executor=executor_flowchart_script(),
        )

        ids = [output.tool_call_id for output in run.transcript.outputs()]
        duplicated = sorted({tc_id for tc_id in ids if ids.count(tc_id) > 1})

        assert duplicated == [], f"streamed twice: {duplicated} (all outputs: {ids})"

    async def test_the_retrieval_hop_the_executor_takes_is_visible_to_the_user(self) -> None:
        """The bind step is work the user is waiting on; it streams as its own
        card, from the same detached task."""
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
        """One timeline for the user: comms' handoff card, then the executor's
        cards, each before the result that fills it in."""
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
        """``call_executor`` is fire-and-forget by design: its tool result is an
        acknowledgement, and the comms reply streams while the work is still
        running. If it ever became blocking the user would stare at nothing."""
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
        """Both tiers stream through the same graph driver; only comms may emit
        ``response`` deltas. Without that gate the executor's own prose is
        interleaved into the assistant bubble the user is reading."""
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
        """The comms ack is persisted BEFORE the executor wait so its position in
        the message array is right; the executor's cards are then pushed onto
        that same message. Saving twice would duplicate the turn, and attaching
        the comms cards again would duplicate every card."""
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
        """Live and reload must agree. The attached entry is the reload's only
        copy of the executor's work, so an entry without its output renders as a
        card that never finished."""
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
    # Three entries for two visible turns: one handoff is below
    # the real-work gate, so the executor's completion guard spends its
    # one nudge before letting the plain-text stop through. The script cycles,
    # so without the repeat the post-nudge turn replays the handoff and the
    # subagent runs twice.
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
        """Scenario 3. Comms opened the stream; the executor and the subagent
        publish onto it from a detached task two levels down."""
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
        """Two hops from where it was emitted. The frontend routes on this key
        alone — untagged, the card renders at the root of the turn instead of
        inside the subagent it belongs to."""
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
        """``subagent_start`` opens the row and ``subagent_end`` closes it. A
        tool card outside that window has no row to render into."""
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
        """The executor acts on this string. A subagent that ran a tool returns
        its own text — not the "re-issue the handoff" narration-only signal."""
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
        """A reload has to show the subagent's work nested, not flattened next to
        the executor's own cards."""
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
    """The executor cannot reach an integration tool itself — its tool space is
    ``general`` and provider namespaces are filtered out of retrieval — so the
    only route is through a subagent. ``gaia_knowledge_guide`` auto-binds
    ``fetch_webpages`` unconditionally, which makes it the one integration tool
    reachable in-process: the tool's body runs for real and only its HTTP GET is
    doubled.

    (The Composio-hosted toolkits — gmail, github, slack, todoist — are covered
    at their own tier by ``test_integration_toolkits.py``, which drives the real
    tool bodies through the real proxy/auth seams. Composing one of them here
    would mean building its subagent graph from a fabricated tool list, so the
    "integration tool" in the chain would not be the real one.)
    """

    async def test_the_tool_is_bound_without_a_retrieval_hop(self) -> None:
        """``auto_bind_tools`` is a promise the subagent's first model call can
        already use it. If the binding silently resolved to nothing, the call
        would come back as a bind rejection instead of a result."""
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
        """``fetch_webpages`` narrates itself over the custom stream. Those
        events cross the subagent driver, the executor driver and Redis before
        the user sees them — three hops that only exist in composition."""
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
        """Pins current behaviour, which is a defect the chain makes visible.

        ``fetch_webpages`` pushes ``{"webpage_data": ..., "fetched_urls": [...]}``
        onto the custom stream as a native card. ``normalize_custom_event`` only
        wraps fields listed in ``tool_fields`` — and ``webpage_data`` is not one
        — so the payload is published verbatim, with no ``tool_data`` envelope
        and therefore no discriminator. ``schema.ts`` has no ``webpage_data``
        either, so the client absorbs it as an unknown frame and renders
        nothing: the page content the user is waiting on reaches them only
        through the tool result and the subagent's prose.

        This is the same class as the ``image_data`` gap already recorded in the
        plan (§6b, absent coverage #3) — an emitted frame key that exists on
        neither side's contract. Whether to register the field or stop emitting
        it is a product decision, so this asserts what ships rather than what
        ought to.
        """
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
        """The tool swallows a per-URL failure and reports it as progress. The
        chain must not take the whole turn down with it — comms already replied
        and its stream is the only thing the user is watching."""
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
