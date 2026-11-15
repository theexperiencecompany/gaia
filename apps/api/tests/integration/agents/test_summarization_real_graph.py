"""Summarization driven through the compiled agent graph that runs in production.

Only the LLM boundary is faked. Everything between it and the checkpoint is the
real code path: create_agent's acall_model, the MiddlewareExecutor, and GAIA's
own WorkspaceArchivingSummarizationMiddleware. The unit suite exercises the
middleware in isolation, so this is the tier that proves it is wired in at all:
which messages the summariser is handed, which survive into the model prompt,
and what the checkpoint holds after several turns.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings as hypothesis_settings, strategies as st
from langchain.agents.middleware.summarization import ContextSize
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.outputs import ChatResult
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.memory import InMemoryStore
from pydantic import Field
import pytest

from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    SUMMARY_SOURCE,
    TIME_CONTEXT_MARKER,
    is_conversation_summary,
    mark,
)
from app.agents.core.graph_manager import GraphManager
from app.agents.middleware.factory import create_comms_history_fold, create_comms_middleware
from app.agents.middleware.summarization import (
    ArchiveReader,
    WorkspaceArchivingSummarizationMiddleware,
)
from app.config.settings import settings
from app.constants.conversation import LOG_SEQ
from app.constants.summarization import (
    COMMS_SUMMARIZATION_TRIGGER_TOKENS,
)
from app.models.conversation_log_models import Batch, LoggedEntry, Reply, StepClaim
from app.override.langgraph_bigtool.agent_config import AgentConfig, ToolRetrievalConfig
from app.override.langgraph_bigtool.create_agent import create_agent
from app.services.conversation.comms_runner import CommsGraphRunner, CommsTurn
from app.services.conversation.ports import FoldPlan, Kept
from tests.helpers import BindableToolsFakeModel
from tests.unit.services.conversation.log_helpers import logged, user

STATIC_PROMPT = "You are GAIA, the user's personal assistant."
SUMMARY = "NEW SUMMARY"


class RecordingModel(BindableToolsFakeModel):
    """Chat model that records the exact message list production hands it."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


class RecordingSummarizer(GenericFakeChatModel):
    """Summarizer fake that records the transcript it was asked to condense."""

    prompts: list[str] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.prompts.append(str(messages[-1].content))
        return super()._generate(messages, *args, **kwargs)


class ExplodingSummarizer(GenericFakeChatModel):
    """Summarizer that fails the way an over-length provider call fails."""

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        raise RuntimeError("400 context_length_exceeded")


def _tool_step(n: int) -> list[BaseMessage]:
    """One completed tool call and its result, as the loop leaves them in the thread."""
    call = AIMessage(
        content="", id=f"call{n}", tool_calls=[{"name": "web_search", "args": {}, "id": f"c{n}"}]
    )
    return [call, ToolMessage(content=f"result {n}", tool_call_id=f"c{n}", id=f"res{n}")]


def _build(
    model: BindableToolsFakeModel,
    summarizer: BaseChatModel,
    *,
    trigger: int | ContextSize,
    keep: int | ContextSize,
    archive: ArchiveReader | None = None,
    tool_registry: Mapping[str, BaseTool] | None = None,
) -> CompiledStateGraph:
    middleware = WorkspaceArchivingSummarizationMiddleware(
        model=summarizer,
        trigger=("messages", trigger) if isinstance(trigger, int) else trigger,
        keep=("messages", keep) if isinstance(keep, int) else keep,
        archive=archive,
    )
    return _compile(model, middleware, tool_registry)


def _compile(
    model: BindableToolsFakeModel,
    middleware: WorkspaceArchivingSummarizationMiddleware,
    tool_registry: Mapping[str, BaseTool] | None = None,
) -> CompiledStateGraph:
    # An ambient GOOGLE_API_KEY would give create_agent a real fallback model,
    # so nothing below would ever reach the fakes this file asserts on.
    with patch.object(settings, "GOOGLE_API_KEY", None):
        builder = create_agent(
            model,
            tool_registry or {},
            tools_config=ToolRetrievalConfig(
                disable_retrieve_tools=True,
                initial_tool_ids=list(tool_registry) if tool_registry else None,
            ),
            agent_config=AgentConfig(middleware=[middleware]),
        )
    return builder.compile(checkpointer=InMemorySaver(), store=InMemoryStore())


@tool("GMAIL_FETCH_MESSAGES")
def gmail_fetch_messages(query: str) -> str:
    """Search the user's Gmail and return integration-sized message records."""
    return json.dumps(
        {
            "query": query,
            "messages": [
                {
                    "id": f"m{i}",
                    "subject": f"Subject {i}",
                    "from": f"person{i}@example.com",
                    "snippet": "x" * 200,
                }
                for i in range(200)
            ],
        }
    )


def _integration_registry() -> dict[str, BaseTool]:
    return {gmail_fetch_messages.name: gmail_fetch_messages}


def _gmail_call(call_id: str, query: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": gmail_fetch_messages.name,
                "args": {"query": query},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _tool_results(messages: list[BaseMessage]) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


def _assert_no_orphan_tool_results(messages: list[BaseMessage]) -> None:
    """Every tool result in the prompt still has the call that produced it."""
    calls = {
        tc["id"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls if tc["id"]
    }
    results = {m.tool_call_id for m in _tool_results(messages)}
    assert results <= calls, f"tool results without their call: {results - calls}"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id, "user_id": "u1"}}


def _summaries(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [m for m in messages if is_conversation_summary(m)]


def _ids(messages: list[BaseMessage]) -> list[str | None]:
    return [m.id for m in messages]


def _running_turn_history() -> list[BaseMessage]:
    """Prompt slots, four finished turns, then the running turn with two tool steps."""
    messages: list[BaseMessage] = [
        SystemMessage(content=STATIC_PROMPT, id="static0"),
        mark(SystemMessage(content="dynamic context", id="dyn0"), DYNAMIC_CONTEXT_MARKER),
        HumanMessage(content="user turn 0", id="h0"),
        mark(HumanMessage(content="[Current UTC Time]", id="time0"), TIME_CONTEXT_MARKER),
        AIMessage(content="assistant turn 0", id="a0"),
    ]
    for i in range(1, 4):
        messages.append(HumanMessage(content=f"user turn {i}", id=f"h{i}"))
        messages.append(AIMessage(content=f"assistant turn {i}", id=f"a{i}"))
    messages.append(HumanMessage(content="current question", id="hcur"))
    messages.append(
        mark(HumanMessage(content="[Current UTC Time]", id="timecur"), TIME_CONTEXT_MARKER)
    )
    messages.extend(_tool_step(1))
    messages.extend(_tool_step(2))
    return messages


@pytest.mark.integration
@pytest.mark.asyncio
class TestRunningTurnAndItsToolSteps:
    """The running turn is in progress: it must reach the model untouched."""

    async def test_prompt_slots_running_turn_and_tool_steps_reach_the_model_verbatim(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=10, keep=2)

        await graph.ainvoke(
            {"messages": _running_turn_history(), "selected_tool_ids": [], "todos": []},
            config=_config("running-tools-1"),
        )

        sent = model.seen[0]
        # The summary takes the first folded id, so the slots stay ahead of it and
        # the preserved tail keeps its exact order and tool pairs. The folded turn's
        # clock goes with it; the running turn's own clock stays beside its request.
        assert _ids(sent) == [
            "static0",
            "dyn0",
            "h0",
            "hcur",
            "timecur",
            "call1",
            "res1",
            "call2",
            "res2",
        ]
        assert sent[0].content == STATIC_PROMPT
        assert sent[1].content == "dynamic context"
        assert sent[4].content == "[Current UTC Time]"
        assert is_conversation_summary(sent[2])
        assert not any(isinstance(m, RemoveMessage) for m in sent)

    async def test_the_summarizer_only_ever_sees_finished_history(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=10, keep=2)

        await graph.ainvoke(
            {"messages": _running_turn_history(), "selected_tool_ids": [], "todos": []},
            config=_config("running-tools-2"),
        )

        prompt = summarizer.prompts[0]
        assert "user turn 1" in prompt and "assistant turn 1" in prompt
        # Neither the request in flight nor the work done for it belongs in history.
        assert "current question" not in prompt
        assert "result 1" not in prompt
        assert "result 2" not in prompt
        # Prompt slots are rebuilt every turn and must survive verbatim instead.
        assert STATIC_PROMPT not in prompt
        assert "dynamic context" not in prompt
        assert "[Current UTC Time]" not in prompt

    async def test_the_folded_prefix_becomes_one_summary_in_the_checkpoint(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=10, keep=2)
        config = _config("running-tools-3")

        await graph.ainvoke(
            {"messages": _running_turn_history(), "selected_tool_ids": [], "todos": []},
            config=config,
        )

        kept = (await graph.aget_state(config)).values["messages"]
        summaries = _summaries(kept)
        assert len(summaries) == 1
        assert summaries[0].id == "h0"
        assert kept[-1].content == "done"


@pytest.mark.integration
@pytest.mark.asyncio
class TestExecutorLongRun:
    """A single delegated task that keeps calling tools is bounded, not frozen."""

    async def test_finished_steps_fold_while_the_delegated_task_is_never_folded(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=4, keep=2)

        history: list[BaseMessage] = [
            HumanMessage(
                content="earlier work",
                additional_kwargs={"lc_source": SUMMARY_SOURCE},
                id="summary",
            ),
            HumanMessage(content="the delegated task", id="task"),
            *_tool_step(1),
            *_tool_step(2),
            *_tool_step(3),
            *_tool_step(4),
        ]
        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []},
            config=_config("executor-long-run"),
        )

        prompt = summarizer.prompts[0]
        # The old summary is folded into the new one rather than dropped, and only
        # steps that already finished fold -- the task itself stays in context.
        assert "earlier work" in prompt
        assert "result 3" in prompt
        assert "the delegated task" not in prompt

        sent = model.seen[0]
        assert _ids(sent) == ["summary", "task", "call4", "res4"]
        assert "the delegated task" in str(sent[1].content)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSuccessiveTurns:
    """Repeated summarization must replace the summary, never stack it."""

    async def test_each_fold_replaces_the_previous_summary_in_place(self):
        model = RecordingModel(responses=[AIMessage(content="done")] * 9)
        summarizer = RecordingSummarizer(
            messages=iter([AIMessage(content=f"SUM-{i}") for i in range(20)])
        )
        graph = _build(model, summarizer, trigger=6, keep=2)
        config = _config("successive-turns")

        history: list[BaseMessage] = []
        for i in range(4):
            history.append(HumanMessage(content=f"user {i}", id=f"h{i}"))
            history.append(AIMessage(content=f"asst {i}", id=f"a{i}"))
        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []}, config=config
        )
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="turn 2", id="t2")],
                "selected_tool_ids": [],
                "todos": [],
            },
            config=config,
        )
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="turn 3", id="t3")],
                "selected_tool_ids": [],
                "todos": [],
            },
            config=config,
        )

        kept = (await graph.aget_state(config)).values["messages"]
        summaries = _summaries(kept)
        assert len(summarizer.prompts) >= 2, "the second turn never re-summarized"
        assert len(summaries) == 1, "summaries accumulated instead of replacing each other"
        assert summaries[0].id == "h0"
        assert "SUM-1" in str(summaries[0].content), "the newest summary is not the one kept"
        assert "turn 3" in str(kept[-2].content)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSummarizerFailure:
    """A summariser that fails must degrade to full context, not lose history."""

    async def test_the_run_completes_with_every_message_still_present(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = ExplodingSummarizer(messages=iter([]), profile={"max_input_tokens": 1_000_000})
        graph = _build(model, summarizer, trigger=4, keep=1)
        config = _config("summarizer-failure")

        history: list[BaseMessage] = []
        for i in range(4):
            history.append(HumanMessage(content=f"user {i}", id=f"h{i}"))
            history.append(AIMessage(content=f"asst {i}", id=f"a{i}"))
        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []}, config=config
        )

        sent = model.seen[0]
        assert _ids(sent) == [f"h{i}" if j == 0 else f"a{i}" for i in range(4) for j in range(2)]
        assert _summaries(sent) == []

        kept = (await graph.aget_state(config)).values["messages"]
        assert len(kept) == len(history) + 1
        assert kept[-1].content == "done"


@pytest.mark.integration
@pytest.mark.asyncio
class TestArchiveBeforeFold:
    """The workspace archive is written before the history it captures is folded away."""

    async def test_the_archive_holds_the_pre_fold_history_and_its_path_reaches_the_summary(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=10, keep=2, archive="read_tool")
        archive_path = "/workspace/sessions/archive-1/archives/pre_summary_x.json"
        written: dict[str, Any] = {}

        async def fake_write(**kwargs: Any) -> tuple[str, str]:
            written.update(kwargs)
            return "/mnt/jfs/x", archive_path

        with patch("app.agents.middleware.summarization.write_session_file", fake_write):
            await graph.ainvoke(
                {"messages": _running_turn_history(), "selected_tool_ids": [], "todos": []},
                config=_config("archive-1"),
            )

        assert written["user_id"] == "u1"
        assert written["conversation_id"] == "archive-1"
        assert written["relative_path"].startswith("archives/pre_summary_")

        archived = json.loads(written["content"])
        assert any(entry["content"] == "user turn 0" for entry in archived)
        assert all(entry["type"] != "RemoveMessage" for entry in archived)

        summary = _summaries(model.seen[0])[0]
        assert summary.additional_kwargs["archive_path"] == archive_path
        assert archive_path in str(summary.content)
        assert "Use the `read` tool" in str(summary.content)

    async def test_a_tier_without_a_read_tool_routes_recovery_to_the_executor(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(
            model,
            summarizer,
            trigger=10,
            keep=2,
            archive="executor",
        )
        archive_path = "/workspace/sessions/archive-1/archives/pre_summary_x.json"

        async def fake_write(**kwargs: Any) -> tuple[str, str]:
            return "/mnt/jfs/x", archive_path

        with patch("app.agents.middleware.summarization.write_session_file", fake_write):
            await graph.ainvoke(
                {"messages": _running_turn_history(), "selected_tool_ids": [], "todos": []},
                config=_config("archive-1"),
            )

        summary = _summaries(model.seen[0])[0]
        assert summary.additional_kwargs["archive_path"] == archive_path
        assert "`call_executor`" in str(summary.content)
        assert "ask the executor to read that file" in str(summary.content)


@pytest.mark.integration
@pytest.mark.asyncio
class TestExecutorRunWithIntegrationTools:
    """A delegated run whose tools return integration-sized output.

    The tool is a real BaseTool executed by the graph's own tool node; only its
    payload is synthetic. Production keep is 8000 tokens, and one Gmail page is
    ~12k, so these tests pin the exact boundary: a finished page folds whole,
    the page still in progress never folds, and a batch never splits.
    """

    async def test_a_finished_integration_step_folds_while_the_next_one_runs(self):
        model = RecordingModel(
            responses=[
                _gmail_call("g1", "unpaid invoices"),
                _gmail_call("g2", "sent mail"),
                AIMessage(content="done"),
            ]
        )
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(
            model,
            summarizer,
            trigger=("tokens", 8000),
            keep=("tokens", 8000),
            tool_registry=_integration_registry(),
        )
        history: list[BaseMessage] = [
            SystemMessage(content=STATIC_PROMPT, id="static0"),
            HumanMessage(content="find my unpaid invoices", id="task"),
        ]

        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []},
            config=_config("executor-integration-sequential"),
        )

        # Only the finished page was folded; the page the run is still working
        # on is the reason the second call happened, not history yet.
        assert len(summarizer.prompts) == 1
        prompt = summarizer.prompts[0]
        assert "unpaid invoices" in prompt
        assert "sent mail" not in prompt
        assert "find my unpaid invoices" not in prompt
        # The system prompt is never summarized.
        assert STATIC_PROMPT not in prompt

        for seen in model.seen:
            assert seen[0].id == "static0"
            assert seen[0].content == STATIC_PROMPT
            _assert_no_orphan_tool_results(seen)

        final = model.seen[-1]
        assert any(getattr(m, "id", None) == "task" for m in final)
        assert len(_summaries(final)) == 1
        remaining = _tool_results(final)
        assert len(remaining) == 1
        assert "sent mail" in str(remaining[0].content)

        kept = (await graph.aget_state(_config("executor-integration-sequential"))).values[
            "messages"
        ]
        assert len(_summaries(kept)) == 1
        assert any(getattr(m, "id", None) == "task" for m in kept)
        assert not any(
            isinstance(m, ToolMessage) and "unpaid invoices" in str(m.content) for m in kept
        )
        assert not any(
            isinstance(m, AIMessage) and any(tc["id"] == "g1" for tc in m.tool_calls) for m in kept
        )

    async def test_a_batched_integration_step_folds_whole_once_the_next_step_starts(self):
        model = RecordingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": gmail_fetch_messages.name,
                            "args": {"query": query},
                            "id": f"g{i}",
                            "type": "tool_call",
                        }
                        for i, query in enumerate(("inbox", "sent", "drafts"), start=1)
                    ],
                ),
                _gmail_call("g4", "archive"),
                AIMessage(content="done"),
            ]
        )
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(
            model,
            summarizer,
            trigger=("tokens", 8000),
            keep=("tokens", 8000),
            tool_registry=_integration_registry(),
        )
        history: list[BaseMessage] = [
            SystemMessage(content=STATIC_PROMPT, id="static0"),
            HumanMessage(content="check all my mail folders", id="task"),
        ]

        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []},
            config=_config("executor-integration-batch"),
        )

        assert len(summarizer.prompts) == 1
        prompt = summarizer.prompts[0]
        assert all(query in prompt for query in ("inbox", "sent", "drafts"))
        assert "archive" not in prompt
        assert "check all my mail folders" not in prompt

        final = model.seen[-1]
        assert len(_summaries(final)) == 1
        remaining = _tool_results(final)
        assert len(remaining) == 1
        assert "archive" in str(remaining[0].content)
        _assert_no_orphan_tool_results(final)

    async def test_a_new_delegation_folds_the_finished_one_not_its_own_task(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        summarizer = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 5))
        graph = _build(model, summarizer, trigger=4, keep=2)
        history: list[BaseMessage] = [
            SystemMessage(content=STATIC_PROMPT, id="static0"),
            HumanMessage(
                content="summary of earlier work",
                additional_kwargs={"lc_source": SUMMARY_SOURCE},
                id="summary",
            ),
            HumanMessage(content="the first delegation", id="old-task"),
            *_tool_step(1),
            *_tool_step(2),
            HumanMessage(content="the second delegation", id="new-task"),
            *_tool_step(3),
        ]

        await graph.ainvoke(
            {"messages": history, "selected_tool_ids": [], "todos": []},
            config=_config("executor-integration-delegations"),
        )

        prompt = summarizer.prompts[0]
        assert "the first delegation" in prompt
        assert "result 1" in prompt and "result 2" in prompt
        assert "the second delegation" not in prompt
        assert "result 3" not in prompt

        sent = model.seen[0]
        assert _ids(sent) == ["static0", "summary", "new-task", "call3", "res3"]
        assert is_conversation_summary(sent[1])
        _assert_no_orphan_tool_results(sent)


# Founder-shaped comms thread: a long prompt slot, then turns that each looked
# something up on the web (comms runs its own lookups) and answered.
_COMMS_PROMPT_CHARS = 68_000
_LOOKUP_RESULT_CHARS = 6_000
_REPLY_CHARS = 1_200


def _comms_summarization(summarizer: BaseChatModel) -> WorkspaceArchivingSummarizationMiddleware:
    """Return the summarization middleware production builds for comms, archiving off."""
    stack = create_comms_middleware(frozenset(), chat_llm=summarizer)
    middleware = next(m for m in stack if isinstance(m, WorkspaceArchivingSummarizationMiddleware))
    middleware.archive = None
    return middleware


def _comms_turns(first: int, count: int) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for n in range(first, first + count):
        call = AIMessage(
            content="",
            id=f"look{n}",
            tool_calls=[{"name": "web_search_tool", "args": {"q": f"q{n}"}, "id": f"w{n}"}],
        )
        messages += [
            HumanMessage(
                content=f"[#{n}] question {n}", id=f"log:u{n}", additional_kwargs={LOG_SEQ: 10 * n}
            ),
            call,
            ToolMessage(content="r" * _LOOKUP_RESULT_CHARS, tool_call_id=f"w{n}", id=f"res{n}"),
            AIMessage(content=f"answer {n} " + "a" * _REPLY_CHARS, id=f"ans{n}"),
        ]
    return messages


def _comms_history(turns: int) -> list[BaseMessage]:
    return [
        SystemMessage(content="p" * _COMMS_PROMPT_CHARS, id="static0"),
        *_comms_turns(0, turns),
        HumanMessage(content="[#999] latest question", id="log:u999"),
    ]


async def _comms_turn(
    graph: CompiledStateGraph, messages: list[BaseMessage], thread_id: str, open_ids: list[str]
) -> None:
    """Run one comms turn the way the runner starts one: its open requests ride on the input."""
    turn = {
        "messages": messages,
        "selected_tool_ids": [],
        "todos": [],
        "verbatim_message_ids": open_ids,
    }
    await graph.ainvoke(turn, config=_config(thread_id))


def _history_fold(summarizer: BaseChatModel) -> CommsGraphRunner:
    """Return the comms runner production folds settled threads with, archiving off."""
    fold = create_comms_history_fold(summarizer)
    fold.archive = None

    async def no_turn(claim: StepClaim, batch: Batch) -> CommsTurn:
        raise AssertionError("a history fold builds no turn")

    return CommsGraphRunner(no_turn, history_fold=fold)


async def _plan(
    graph: CompiledStateGraph,
    runner: CommsGraphRunner,
    thread_id: str,
    owed: frozenset[str] = frozenset(),
    pinned: tuple[LoggedEntry, ...] = (),
) -> FoldPlan:
    with patch.object(GraphManager, "get_graph", AsyncMock(return_value=graph)):
        plan = await runner.plan_fold(thread_id, "u1", Kept(owed, pinned))
    assert plan is not None
    return plan


async def _apply(
    graph: CompiledStateGraph, runner: CommsGraphRunner, thread_id: str, plan: FoldPlan
) -> bool:
    claim = StepClaim(conversation_id=thread_id, user_id="u1", epoch=1)
    with patch.object(GraphManager, "get_graph", AsyncMock(return_value=graph)):
        return await runner.apply_fold(claim, plan)


async def _thread(graph: CompiledStateGraph, thread_id: str) -> list[BaseMessage]:
    return (await graph.aget_state(_config(thread_id))).values["messages"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestCommsHistoryFoldOffTheReplyPath:
    """A settled comms thread past its budget folds in the background; no turn waits on the summary."""

    async def test_a_turn_over_the_trigger_never_calls_the_summarizer(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        inline = RecordingSummarizer(messages=iter([]))
        graph = _compile(model, _comms_summarization(inline))
        history = _comms_history(50)
        assert count_tokens_approximately(history) > COMMS_SUMMARIZATION_TRIGGER_TOKENS

        await _comms_turn(graph, history, "comms-hot", [])

        assert inline.prompts == []
        assert _ids(model.seen[0]) == _ids(history)

    async def test_the_background_fold_writes_the_summary_and_the_next_turn_reads_it(self):
        model = RecordingModel(responses=[AIMessage(content="done")] * 2)
        inline = RecordingSummarizer(messages=iter([]))
        graph = _compile(model, _comms_summarization(inline))
        background = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)]))
        runner = _history_fold(background)
        history = _comms_history(50)
        await _comms_turn(graph, history, "comms-fold", [])

        plan = await _plan(graph, runner, "comms-fold", owed=frozenset({"u3", "u20"}))
        assert await _apply(graph, runner, "comms-fold", plan)
        latest = HumanMessage(content="[#1000] next question", id="log:u1000")
        await _comms_turn(graph, [latest], "comms-fold", [])

        assert inline.prompts == []
        sent = model.seen[1]
        assert count_tokens_approximately(sent) <= COMMS_SUMMARIZATION_TRIGGER_TOKENS
        # Cache-friendly prefix: the stable prompt, then the summary, then what stayed.
        assert sent[0].id == "static0"
        assert is_conversation_summary(sent[1])
        assert SUMMARY in str(sent[1].content)
        assert sent[-1].content == "[#1000] next question"
        verbatim = {m.id: m.content for m in history}
        kept = [m for m in sent[2:] if m.id in verbatim]
        assert all(m.content == verbatim[m.id] for m in kept)
        assert [m.content for m in kept if m.id in {"log:u3", "log:u20"}] == [
            "[#3] question 3",
            "[#20] question 20",
        ]
        assert "[#3] question 3" not in background.prompts[0]
        assert "[#4] question 4" in background.prompts[0]
        _assert_no_orphan_tool_results(sent)

    async def test_a_turn_between_plan_and_apply_loses_no_message(self):
        model = RecordingModel(responses=[AIMessage(content="done", id="done1")] * 2)
        graph = _compile(model, _comms_summarization(RecordingSummarizer(messages=iter([]))))
        background = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)] * 2))
        runner = _history_fold(background)
        await _comms_turn(graph, _comms_history(50), "comms-race", [])

        stale = await _plan(graph, runner, "comms-race")
        racing = HumanMessage(content="[#1000] asked while folding", id="log:u1000")
        await _comms_turn(graph, [racing], "comms-race", [])
        before = await _thread(graph, "comms-race")

        assert not await _apply(graph, runner, "comms-race", stale)
        assert _ids(await _thread(graph, "comms-race")) == _ids(before)
        assert _summaries(before) == []

        assert await _apply(graph, runner, "comms-race", await _plan(graph, runner, "comms-race"))
        folded = await _thread(graph, "comms-race")
        assert [m.content for m in folded if m.id == "log:u1000"] == ["[#1000] asked while folding"]
        assert len(_summaries(folded)) == 1

    async def test_pinned_messages_and_replies_stay_verbatim(self):
        model = RecordingModel(responses=[AIMessage(content="done")])
        graph = _compile(model, _comms_summarization(RecordingSummarizer(messages=iter([]))))
        background = RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)]))
        runner = _history_fold(background)
        history = _comms_history(50)
        await _comms_turn(graph, history, "comms-pins", [])
        # Turn n's question is logged at seq 10n; its reply opens just after, at 10n + 5.
        pinned = (
            logged(30, user("u3")),
            logged(55, Reply(id="r5", reply_id="r5", attempt_id="a5", pinned=True)),
        )

        plan = await _plan(graph, runner, "comms-pins", pinned=pinned)
        assert await _apply(graph, runner, "comms-pins", plan)

        by_id = {m.id: m.content for m in await _thread(graph, "comms-pins")}
        verbatim = {m.id: m.content for m in history}
        assert by_id["log:u3"] == verbatim["log:u3"]
        assert by_id["ans5"] == verbatim["ans5"]
        assert "ans4" not in by_id
        prompt = background.prompts[0]
        assert "[#3] question 3" not in prompt
        assert "answer 5 a" not in prompt
        assert "answer 4 a" in prompt

    async def test_the_summary_rolls_forward_from_the_last_one(self):
        model = RecordingModel(responses=[AIMessage(content="done")] * 2)
        graph = _compile(model, _comms_summarization(RecordingSummarizer(messages=iter([]))))
        background = RecordingSummarizer(
            messages=iter([AIMessage(content=f"SUM-{i}") for i in range(2)])
        )
        runner = _history_fold(background)
        owed = frozenset({"u3"})

        await _comms_turn(graph, _comms_history(50), "comms-rolling", [])
        await _apply(
            graph, runner, "comms-rolling", await _plan(graph, runner, "comms-rolling", owed)
        )
        later = [*_comms_turns(100, 40), HumanMessage(content="next", id="next")]
        await _comms_turn(graph, later, "comms-rolling", [])
        await _apply(
            graph, runner, "comms-rolling", await _plan(graph, runner, "comms-rolling", owed)
        )

        assert len(background.prompts) == 2
        second = background.prompts[1]
        # Only the new overflow is read again, on top of the last summary.
        assert "SUM-0" in second
        assert "[#4] question 4" not in second
        assert "[#100] question 100" in second
        kept = await _thread(graph, "comms-rolling")
        summaries = [str(m.content) for m in _summaries(kept)]
        assert len(summaries) == 1
        assert summaries[0].endswith("SUM-1")
        assert "[#3] question 3" in [m.content for m in kept]


@pytest.mark.integration
@hypothesis_settings(max_examples=20, deadline=None)
@given(
    turns=st.integers(min_value=30, max_value=60),
    open_turns=st.sets(st.integers(min_value=0, max_value=59), max_size=6),
)
def test_open_requests_always_reach_comms_verbatim(turns: int, open_turns: set[int]) -> None:
    model = RecordingModel(responses=[AIMessage(content="done")])
    graph = _compile(model, _comms_summarization(RecordingSummarizer(messages=iter([]))))
    runner = _history_fold(RecordingSummarizer(messages=iter([AIMessage(content=SUMMARY)])))
    owed = frozenset(f"u{n}" for n in open_turns if n < turns)

    async def turn_then_fold() -> list[BaseMessage]:
        await _comms_turn(graph, _comms_history(turns), "comms-prop", [])
        await _apply(graph, runner, "comms-prop", await _plan(graph, runner, "comms-prop", owed))
        return await _thread(graph, "comms-prop")

    folded = asyncio.run(turn_then_fold())

    by_id = {m.id: m.content for m in folded}
    assert all(by_id.get(f"log:u{n}") == f"[#{n}] question {n}" for n in open_turns if n < turns)
    assert count_tokens_approximately(folded) <= COMMS_SUMMARIZATION_TRIGGER_TOKENS
