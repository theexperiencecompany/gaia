"""Unit tests for the agent-config leaf.

Imports app.models.agent_config directly, not the agent_models re-export: the
mutation matrix maps a module to the tests that name it, and every other caller
reaches these symbols through the re-export.
"""

from app.models.agent_config import (
    CONFIGURABLE_KEY,
    AgentConfigurableView,
    agent_configurable,
    read_agent_configurable,
)


class TestAgentConfigurable:
    def test_no_config_at_all_reads_as_an_empty_bag(self) -> None:
        assert agent_configurable(None) == {}

    def test_a_config_without_the_key_reads_as_an_empty_bag(self) -> None:
        assert agent_configurable({"tags": ["x"]}) == {}

    def test_a_null_configurable_reads_as_an_empty_bag(self) -> None:
        """LangGraph writes the key before filling it, so None must not leak out."""
        assert agent_configurable({CONFIGURABLE_KEY: None}) == {}

    def test_the_owned_keys_are_returned_as_written(self) -> None:
        bag = {"user_id": "u1", "thread_id": "t1"}
        assert agent_configurable({CONFIGURABLE_KEY: bag}) == bag

    def test_langgraphs_own_runtime_keys_ride_along_untouched(self) -> None:
        bag = {"user_id": "u1", "checkpoint_ns": "ns"}
        assert agent_configurable({CONFIGURABLE_KEY: bag})["checkpoint_ns"] == "ns"


class TestReadAgentConfigurable:
    def test_an_empty_config_parses_to_all_defaults(self) -> None:
        view = read_agent_configurable(None)
        assert isinstance(view, AgentConfigurableView)
        assert view.user_id is None
        assert view.workflow_title == ""
        assert view.workflow_notify_on_completion is True

    def test_the_declared_keys_are_parsed_onto_attributes(self) -> None:
        view = read_agent_configurable(
            {CONFIGURABLE_KEY: {"user_id": "u1", "user_timezone": "+05:30"}}
        )
        assert view.user_id == "u1"
        assert view.user_timezone == "+05:30"

    def test_a_key_nobody_declared_is_ignored_rather_than_raising(self) -> None:
        """LangGraph merges its own keys in, so the view must tolerate them."""
        view = read_agent_configurable({CONFIGURABLE_KEY: {"__pregel_task_id": "x"}})
        assert not hasattr(view, "__pregel_task_id")

    def test_an_absent_key_is_distinguishable_from_one_carried_as_none(self) -> None:
        carried = read_agent_configurable({CONFIGURABLE_KEY: {"session_id": None}})
        absent = read_agent_configurable({CONFIGURABLE_KEY: {}})
        assert "session_id" in carried.model_fields_set
        assert "session_id" not in absent.model_fields_set
