"""Unit tests for `app.models.subagent_models`.

UNIT: app/models/subagent_models.py :: Subagent
EXPECTED: `Subagent` is the canonical, value-semantic handle for a delegated
    agent. It carries five required identity fields (id, name, provider,
    managed_by, config) and two optional ones (short_name, mcp_config). It is
    immutable, compared by value, and memory-compact.
MECHANISM: a `@dataclass(frozen=True, slots=True)`. `frozen=True` blocks
    attribute reassignment (raises FrozenInstanceError) and synthesises a
    value-based `__eq__` + `__hash__`. `slots=True` gives instances `__slots__`
    instead of a per-instance `__dict__`. `short_name` / `mcp_config` default to
    `None`. The `config` field is a Pydantic `SubAgentConfig`, which is not
    hashable, so `hash(Subagent)` propagates a TypeError.
MUST-CATCH:
    - Required fields are stored verbatim (id/name/provider/managed_by/config).
    - Optional fields default to None, and accept supplied values.
    - frozen=True: reassigning ANY field raises FrozenInstanceError.
      (kills the `frozen=True -> False` mutant.)
    - slots=True: instances have no __dict__ / the class declares __slots__.
      (kills the `slots=True -> False` mutant.)
    - Value equality: same field values compare equal; differing id compares
      unequal (exercises the synthesised __eq__).
    - Unhashable config propagates TypeError on hash().
EQUIVALENT MUTANTS: the four `const_str -> ''` mutants on the
    `managed_by: Literal["self", "composio", "mcp", "internal"]` annotation
    survive and are PROVEN EQUIVALENT. A plain `@dataclass` performs ZERO
    runtime validation of `Literal` annotations — `managed_by` accepts any
    string at runtime (verified: `Subagent(..., managed_by="bogus")` constructs
    fine). Blanking a Literal member changes only static type-checker info, never
    any runtime behaviour a test could assert. No test can or should kill them.
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
    def test_required_fields_are_stored_verbatim(self) -> None:
        config = _make_config()
        subagent = Subagent(
            id="sub-1",
            name="Display Name",
            provider="github",
            managed_by="composio",
            config=config,
        )

        assert subagent.id == "sub-1"
        assert subagent.name == "Display Name"
        assert subagent.provider == "github"
        assert subagent.managed_by == "composio"
        assert subagent.config is config

    def test_optional_fields_default_to_none(self) -> None:
        subagent = _make_subagent()

        assert subagent.short_name is None
        assert subagent.mcp_config is None

    def test_optional_fields_accept_supplied_values(self) -> None:
        mcp_config = MCPConfig(server_url="https://example.com/mcp")
        subagent = _make_subagent(short_name="t", mcp_config=mcp_config)

        assert subagent.short_name == "t"
        assert subagent.mcp_config is mcp_config


@pytest.mark.unit
class TestSubagentImmutability:
    """`frozen=True` is the value-semantics guarantee: a Subagent cannot be
    mutated after construction. Reassigning any field must raise."""

    def test_reassigning_required_field_raises(self) -> None:
        subagent = _make_subagent()

        with pytest.raises(dataclasses.FrozenInstanceError):
            subagent.id = "mutated"  # type: ignore[misc]

    def test_reassigning_optional_field_raises(self) -> None:
        subagent = _make_subagent()

        with pytest.raises(dataclasses.FrozenInstanceError):
            subagent.short_name = "x"  # type: ignore[misc]


@pytest.mark.unit
class TestSubagentSlots:
    """`slots=True` makes instances memory-compact: they get `__slots__` and no
    per-instance `__dict__`. Without slots, dataclass instances carry a
    `__dict__`. Asserting its absence pins the `slots=True` decorator argument."""

    def test_instance_has_no_instance_dict(self) -> None:
        subagent = _make_subagent()

        assert not hasattr(subagent, "__dict__")

    def test_class_declares_slots_for_every_field(self) -> None:
        assert hasattr(Subagent, "__slots__")
        assert set(Subagent.__slots__) == {
            "id",
            "name",
            "provider",
            "managed_by",
            "config",
            "short_name",
            "mcp_config",
        }


@pytest.mark.unit
class TestSubagentEquality:
    def test_equal_field_values_compare_equal(self) -> None:
        # Reuse the SAME config instance — SubAgentConfig is a Pydantic model
        # whose equality is by-field, but we keep identity here so the test is
        # robust regardless of Pydantic's __eq__ semantics.
        config = _make_config()
        a = Subagent(id="x", name="X", provider="x", managed_by="internal", config=config)
        b = Subagent(id="x", name="X", provider="x", managed_by="internal", config=config)

        assert a == b

    def test_different_id_compares_unequal(self) -> None:
        config = _make_config()
        a = Subagent(id="x", name="X", provider="x", managed_by="internal", config=config)
        b = Subagent(id="y", name="X", provider="x", managed_by="internal", config=config)

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
