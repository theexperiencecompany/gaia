"""Unit tests for `app.models.subagent_models`.

Covers the `Subagent` frozen dataclass: required-field construction, default
values, immutability, equality, and hashability.
"""

import dataclasses

import pytest

from app.models.mcp_config import MCPConfig, SubAgentConfig
from app.models.subagent_models import Subagent


def _make_config() -> SubAgentConfig:
    return SubAgentConfig(
        has_subagent=True,
        agent_name="test_agent",
        tool_space="test_space",
        handoff_tool_name="call_test",
        domain="test domain",
        capabilities="test capabilities",
        use_cases="test use cases",
        system_prompt="You are the test agent.",
    )


def _make_subagent(**overrides: object) -> Subagent:
    fields: dict[str, object] = {
        "id": "test",
        "name": "Test",
        "provider": "test",
        "managed_by": "internal",
        "config": _make_config(),
    }
    fields.update(overrides)
    return Subagent(**fields)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSubagentConstruction:
    def test_constructs_with_required_fields_only(self) -> None:
        config = _make_config()
        subagent = Subagent(
            id="test",
            name="Test",
            provider="test",
            managed_by="internal",
            config=config,
        )

        assert subagent.id == "test"
        assert subagent.name == "Test"
        assert subagent.provider == "test"
        assert subagent.managed_by == "internal"
        assert subagent.config is config

    def test_optional_fields_default_to_none(self) -> None:
        subagent = _make_subagent()

        assert subagent.short_name is None
        assert subagent.mcp_config is None

    def test_optional_fields_accept_values(self) -> None:
        mcp_config = MCPConfig(server_url="https://example.com/mcp")
        subagent = _make_subagent(short_name="t", mcp_config=mcp_config)

        assert subagent.short_name == "t"
        assert subagent.mcp_config is mcp_config


@pytest.mark.unit
class TestSubagentImmutability:
    def test_is_frozen(self) -> None:
        subagent = _make_subagent()

        with pytest.raises(dataclasses.FrozenInstanceError):
            subagent.id = "mutated"  # type: ignore[misc]

    def test_frozen_blocks_optional_field_assignment(self) -> None:
        subagent = _make_subagent()

        with pytest.raises(dataclasses.FrozenInstanceError):
            subagent.short_name = "x"  # type: ignore[misc]


@pytest.mark.unit
class TestSubagentEquality:
    def test_equal_field_values_compare_equal(self) -> None:
        # Reuse the SAME config instance — SubAgentConfig is a Pydantic model
        # whose equality is by-field, but we keep identity here so the test is
        # robust regardless of Pydantic's __eq__ semantics.
        config = _make_config()
        a = Subagent(
            id="x", name="X", provider="x", managed_by="internal", config=config
        )
        b = Subagent(
            id="x", name="X", provider="x", managed_by="internal", config=config
        )

        assert a == b

    def test_different_id_compares_unequal(self) -> None:
        config = _make_config()
        a = Subagent(
            id="x", name="X", provider="x", managed_by="internal", config=config
        )
        b = Subagent(
            id="y", name="X", provider="x", managed_by="internal", config=config
        )

        assert a != b


@pytest.mark.unit
class TestSubagentHashability:
    """`Subagent` is a frozen dataclass, so it requests `__hash__`. But its
    `config` field is a Pydantic `BaseModel`, which is not hashable by default —
    so hashing the dataclass propagates a `TypeError`. The dataclass is
    "frozen" for value-semantic safety, not for use as a dict key.

    If this assertion ever fails (e.g., Pydantic gains hashability), revisit
    whether `Subagent` should advertise itself as a hashable key.
    """

    def test_subagent_is_not_hashable(self) -> None:
        subagent = _make_subagent()

        with pytest.raises(TypeError):
            hash(subagent)
