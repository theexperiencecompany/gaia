"""Reading a run's config from outside the run must not raise.

``current_run_config`` and ``agent_configurable`` are how middleware and helpers
reach the ambient LangGraph config: the hooks are called as ``(state, runtime)``
or ``(request, handler)`` and never receive it as a parameter. Both are reached
from sync fallback paths and from code that also runs outside a graph, so an
empty answer is the contract — a raise there would take down a turn over a
missing dict.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
import pytest

from app.models.agent_models import agent_configurable, current_run_config


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
