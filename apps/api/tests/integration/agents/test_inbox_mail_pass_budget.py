"""A spawn finishes a mail sweep inside its step budget however many threads it reads.

The Inbox desk mail pass is the measured case: fetch, mine the saved file, read the
threads, draft, report. A chat sweep slice has the same shape, so every spawn gets
the budget this pass needs, with nothing stamped on the run that spawns it.

Real: the spawn_subagent tool (blocking), the compiled spawn graph with the real middleware
stack, and the recursion wrap-up notice. Replaced: the LLM (a fake that walks the batched mail
pass INBOX_DESK_MAIL_TASK prescribes and, like a real model, answers at once when told it is out
of steps), the Gmail tools (stand-ins with the real names) and the context, store, checkpointer
and HIL-preference seams. Not exercised: a real model's tool choice, real Gmail.
"""

from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
import pytest

from app.agents.context.assemble import AssembledContext
from app.agents.core.subagents import spawn_agent
from app.agents.core.subagents.spawn_agent import get_spawn_graph
from app.agents.middleware.factory import SubagentStackOptions, create_subagent_middleware
from app.agents.middleware.subagent import SubagentMiddleware, SubagentMiddlewareConfig
from app.agents.tools.core.tool_runtime_config import ToolRuntimeConfig
from app.constants.general import FINISH_TASK_NAME
from app.models.agent_models import AnyAgentMiddleware
from tests.helpers import PassthroughFakeLLM

WRAP_UP_MARKER = "almost out of steps"


class MailPassFakeLLM(PassthroughFakeLLM):
    """Walks the batched mail pass one turn per stage, read off the tool results it has seen."""

    def __init__(self, thread_count: int) -> None:
        self.thread_ids = [f"thread-{index}" for index in range(thread_count)]
        self.saw_wrap_up = False
        self.reported: str | None = None

    def _turn(self, stage: int) -> list[dict[str, Any]]:
        if stage == 0:
            return [{"name": "retrieve_gmail_tools", "args": {}}]
        if stage == 1:
            return [
                {"name": "GMAIL_FETCH_MESSAGES", "args": {"query": "after:1790000000 -in:spam"}},
                {"name": "GMAIL_FETCH_MESSAGES", "args": {"query": "after:1790000000"}},
            ]
        if stage == 2:
            return [{"name": "query_json", "args": {"path": "/sweep.jsonl"}}]
        if stage == 3:
            return [{"name": "GMAIL_FETCH_THREAD", "args": {"thread_ids": self.thread_ids}}]
        if stage == 4:
            return [
                {"name": "GMAIL_CREATE_EMAIL_DRAFT", "args": {"thread_id": thread_id}}
                for thread_id in self.thread_ids
            ]
        lines = "\n".join(f"thread: {thread_id} | TO_REPLY" for thread_id in self.thread_ids)
        return [{"name": FINISH_TASK_NAME, "args": {"result": lines}}]

    async def ainvoke(self, messages: Any, **_kwargs: Any) -> AIMessage:
        if any(WRAP_UP_MARKER in str(getattr(m, "content", "")) for m in messages):
            self.saw_wrap_up = True
            self.reported = "partial: ran out of steps"
            return AIMessage(content=self.reported)
        stage = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
        calls = self._turn(stage)
        if calls[0]["name"] == FINISH_TASK_NAME:
            self.reported = calls[0]["args"]["result"]
        return AIMessage(
            content="",
            tool_calls=[{**call, "id": f"s{stage}-{index}"} for index, call in enumerate(calls)],
        )


def _mail_tools() -> dict[str, Any]:
    @tool
    async def retrieve_gmail_tools() -> str:
        """Load the Gmail tools (the pass's one retrieve_tools call)."""
        return "loaded"

    @tool
    async def GMAIL_FETCH_MESSAGES(query: str) -> str:
        """Fetch the window's messages."""
        return f"fetched {query}"

    @tool
    async def query_json(path: str) -> str:
        """Count a saved sweep per sender."""
        return f"counted {path}"

    @tool
    async def GMAIL_FETCH_THREAD(thread_ids: list[str]) -> str:
        """Read every kept thread in one batch."""
        return f"read {len(thread_ids)} threads"

    @tool
    async def GMAIL_CREATE_EMAIL_DRAFT(thread_id: str) -> str:
        """Save one reply draft."""
        return f"draft for {thread_id}"

    return {
        t.name: t
        for t in (
            retrieve_gmail_tools,
            GMAIL_FETCH_MESSAGES,
            query_json,
            GMAIL_FETCH_THREAD,
            GMAIL_CREATE_EMAIL_DRAFT,
        )
    }


async def _run_mail_pass(llm: MailPassFakeLLM) -> list[ToolMessage]:
    """Run one blocking spawn; return the spawn thread's tool results."""
    saver = InMemorySaver()
    tools = _mail_tools()
    holder: dict[str, Any] = {}

    async def provider(
        llm: LanguageModelLike,
        registry: Mapping[str, BaseTool],
        excluded_tool_names: set[str],
        tool_space: str,
        runtime: ToolRuntimeConfig,
        middleware_factory: Callable[[], Sequence[AnyAgentMiddleware]],
    ) -> CompiledStateGraph:
        graph = await get_spawn_graph(
            llm=llm,
            registry=registry,
            excluded_tool_names=excluded_tool_names,
            tool_space=tool_space,
            runtime=runtime,
            middleware_factory=middleware_factory,
        )
        graph.checkpointer = saver
        holder["graph"] = graph
        return graph

    middleware = SubagentMiddleware(
        SubagentMiddlewareConfig(
            llm=cast(LanguageModelLike, llm),
            tool_registry=tools,
            tool_space="general",
            tool_runtime_config=ToolRuntimeConfig(
                initial_tool_names=[*tools, FINISH_TASK_NAME],
                enable_retrieve_tools=False,
                include_subagents_in_retrieve=False,
            ),
            spawn_middleware_factory=lambda space: create_subagent_middleware(
                subagent=SubagentStackOptions(enabled=False, tool_space=space)
            ),
        )
    )
    middleware.set_spawn_graph_provider(provider)
    conv = "mail-pass-conv"
    config: RunnableConfig = {
        "configurable": {
            "thread_id": f"executor_{conv}",
            "conversation_id": conv,
            "user_id": "user-1",
            "email": "desk@test.local",
            "user_name": "Desk",
            "stream_id": "stream-mail-pass",
            "execution_mode": "background",
        }
    }
    spawn = middleware.tools[0]
    assert isinstance(spawn, StructuredTool) and spawn.coroutine is not None
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
            AsyncMock(return_value=SimpleNamespace(get_category_of_tool=lambda _name: "gmail")),
        ),
        patch("app.services.hil.preferences.user_repository.get", AsyncMock(return_value=None)),
    ):
        await spawn.coroutine(
            task="Inbox desk mail pass for Gmail account acct-1.",
            tool_call_id="tc-mail",
            selected_tool_ids=[],
            config=config,
            background=False,
        )
        snapshot = await holder["graph"].aget_state(
            {"configurable": {"thread_id": f"spawn_{conv}_tc-mail"}}
        )
    return [m for m in snapshot.values["messages"] if isinstance(m, ToolMessage)]


@pytest.fixture(autouse=True)
def _fresh_spawn_graphs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spawn_agent, "_graph_cache", {})


@pytest.mark.parametrize("thread_count", [3, 60])
async def test_a_mail_pass_reads_and_drafts_every_thread_within_its_budget(
    thread_count: int,
) -> None:
    llm = MailPassFakeLLM(thread_count)

    results = await _run_mail_pass(llm)

    assert not llm.saw_wrap_up, "the pass was told to stop before it finished"
    drafts = [m for m in results if m.name == "GMAIL_CREATE_EMAIL_DRAFT"]
    assert len(drafts) == thread_count
    assert llm.reported is not None
    assert llm.reported.count("thread: ") == thread_count
