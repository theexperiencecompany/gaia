"""The comms drain hook: inert on runs the conversation runner did not start, and each fed message drains once."""

from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.memory import InMemoryStore

from app.agents.core.background.executor_queue import safe_configurable
from app.agents.core.nodes.drain_conversation_log import (
    close_feed,
    drain_conversation_log_hook,
    feed,
    open_feed,
)
from app.models.agent_models import AgentConfigurable
from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY, State

ASKED = HumanMessage(content="first", id="log:u1")
JOINED = HumanMessage(content="later", id="log:u2")


def state() -> State:
    return cast(State, {"messages": [ASKED]})


def config(run: str | None) -> RunnableConfig:
    return {"configurable": {} if run is None else {"comms_run": run}}


async def test_a_run_the_runner_did_not_start_is_left_alone() -> None:
    open_feed("r1")
    feed("r1", [JOINED])
    try:
        assert await drain_conversation_log_hook(state(), config(None), InMemoryStore()) == state()
    finally:
        close_feed("r1")


async def test_fed_messages_join_the_next_call_once() -> None:
    open_feed("r1")
    feed("r1", [JOINED])
    try:
        first = await drain_conversation_log_hook(state(), config("r1"), InMemoryStore())
        again = await drain_conversation_log_hook(state(), config("r1"), InMemoryStore())
    finally:
        close_feed("r1")
    assert first["messages"] == [ASKED, JOINED]
    assert cast(dict[str, object], first)[INJECTED_MESSAGES_KEY] == [JOINED]
    assert again == state()


async def test_a_closed_feed_drains_nothing() -> None:
    open_feed("r1")
    feed("r1", [JOINED])
    close_feed("r1")
    assert await drain_conversation_log_hook(state(), config("r1"), InMemoryStore()) == state()


def test_a_queued_run_never_carries_the_attempt_feed() -> None:
    queued = safe_configurable(cast(AgentConfigurable, {"thread_id": "t", "comms_run": "r1"}))
    assert queued == {"thread_id": "t"}
