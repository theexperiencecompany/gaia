"""The harness's own contract: it must be hermetic and deterministic.

Everything else in this directory asserts on what the harness produces, so these
run first — a harness that quietly reached Redis, or that returned a different
array on the second call, would make every one of those assertions meaningless.
"""

from collections.abc import Callable
import importlib
from typing import Any

import pytest
from tests._harness.context_chain import AgentTier, effective_context
from tests._harness.context_sources import (
    _FENCED_CLIENTS,
    ContextSources,
    EscapedIO,
    fake_context_sources,
)


def _resolve(dotted: str) -> Callable[..., Any]:
    """Resolve a patch target, which may name a class attribute rather than a
    module-level one (``pkg.mod.Class.method``)."""
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            obj: Any = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for attr in parts[split:]:
            obj = getattr(obj, attr)
        return obj
    raise AssertionError(f"no module prefix of {dotted} is importable")


@pytest.mark.unit
class TestHarnessIsHermetic:
    @pytest.mark.parametrize("target", _FENCED_CLIENTS)
    async def test_reaching_a_real_client_raises(self, target: str) -> None:
        """The fence is what makes 'no IO escaped' a fact rather than a hope.

        Without this, a fence that silently stopped patching (a moved module, a
        renamed function) would look exactly like a hermetic run.
        """
        with fake_context_sources(ContextSources()):
            with pytest.raises(EscapedIO):
                await _resolve(target)()


@pytest.mark.unit
class TestHarnessIsDeterministic:
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_two_identical_runs_are_byte_identical(self, tier: AgentTier) -> None:
        first = await effective_context(tier)
        second = await effective_context(tier)

        assert [(m.type, m.content) for m in first] == [(m.type, m.content) for m in second]

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_every_tier_produces_a_non_empty_array(self, tier: AgentTier) -> None:
        assert await effective_context(tier)
