"""Summarization driven through the compiled agent graph that runs in production.

Only the LLM boundary is faked. Everything between it and the checkpoint is the
real code path: create_agent's acall_model, the MiddlewareExecutor, and GAIA's
own WorkspaceArchivingSummarizationMiddleware. The unit suite exercises the
middleware in isolation, so this is the tier that proves it is wired in at all:
which messages the summariser is handed, which survive into the model prompt,
and what the checkpoint holds after several turns.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any
from unittest.mock import patch

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
from app.agents.middleware.summarization import (
    ArchiveReader,
    WorkspaceArchivingSummarizationMiddleware,
)
from app.config.settings import settings
from app.override.langgraph_bigtool.create_agent import (
    AgentConfig,
    ToolRetrievalConfig,
    create_agent,
)
from tests.helpers import BindableToolsFakeModel

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
    trigger: int | tuple[str, int],
    keep: int | tuple[str, int],
    archive: ArchiveReader | None = None,
    tool_registry: Mapping[str, BaseTool] | None = None,
) -> CompiledStateGraph:
    middleware = [
        WorkspaceArchivingSummarizationMiddleware(
            model=summarizer,
            trigger=trigger if isinstance(trigger, tuple) else ("messages", trigger),
            keep=keep if isinstance(keep, tuple) else ("messages", keep),
            archive=archive,
        )
    ]
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
            agent_config=AgentConfig(middleware=middleware),
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
        # the preserved tail keeps its exact order and tool pairs.
        assert _ids(sent) == [
            "static0",
            "dyn0",
            "h0",
            "time0",
            "hcur",
            "call1",
            "res1",
            "call2",
            "res2",
        ]
        assert sent[0].content == STATIC_PROMPT
        assert sent[1].content == "dynamic context"
        assert sent[3].content == "[Current UTC Time]"
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
