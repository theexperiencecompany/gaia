"""Reading a run's config from outside the run must not raise.

current_run_config and agent_configurable are how middleware and helpers
reach the ambient LangGraph config: the hooks are called as (state, runtime)
or (request, handler) and never receive it as a parameter. Both are reached
from sync fallback paths and from code that also runs outside a graph, so an
empty answer is the contract — a raise there would take down a turn over a
missing dict. current_stream_writer is the same contract for the custom stream.
"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.graph import START, StateGraph
import pytest

from app.agents.tools.execute.dispatch import dispatch_config_for
from app.models.agent_models import (
    agent_configurable,
    current_run_config,
    current_stream_writer,
)


@pytest.mark.unit
def test_the_run_config_is_empty_outside_a_graph_run() -> None:
    assert current_run_config() == {}


@pytest.mark.unit
def test_a_config_with_no_configurable_reads_as_empty() -> None:
    assert agent_configurable(RunnableConfig()) == {}


@pytest.mark.unit
def test_no_config_at_all_reads_as_empty() -> None:
    assert agent_configurable(None) == {}


@pytest.mark.unit
def test_the_gaia_keys_are_read_through_unchanged() -> None:
    config: RunnableConfig = {"configurable": {"user_id": "u1", "execution_mode": "background"}}

    assert agent_configurable(config).get("user_id") == "u1"
    assert agent_configurable(config).get("execution_mode") == "background"


class _StreamState(TypedDict):
    done: bool


def _write_card(_state: _StreamState) -> _StreamState:
    current_stream_writer()({"card": "inline"})
    return {"done": True}


@pytest.mark.unit
def test_inside_a_graph_run_the_writer_reaches_the_custom_stream() -> None:
    graph = StateGraph(_StreamState).add_node("write", _write_card)
    graph.add_edge(START, "write")

    chunks = list(graph.compile().stream({"done": False}, stream_mode="custom"))

    assert chunks == [{"card": "inline"}]


@pytest.mark.unit
def test_a_sandbox_dispatch_config_with_no_graph_runtime_drops_the_write() -> None:
    """The sandbox route runs tools under a synthesized config that has no Pregel runtime."""
    result = RunnableLambda(lambda _: _write_card({"done": False})).invoke(
        None, config=dispatch_config_for("u1")
    )

    assert result == {"done": True}


@pytest.mark.unit
def test_outside_any_runnable_context_the_write_is_dropped() -> None:
    assert _write_card({"done": False}) == {"done": True}
