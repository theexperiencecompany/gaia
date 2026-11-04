"""The fake models' errors belong to the scenario that made them.

Regression for #1610's CI run: one scenario's "step 1 waited past its patience"
stayed in the module's error list, and every later scenario's errors == [] failed on it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from tests.integration.real.browser._stack.fake_models import FakeModels

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def models() -> AsyncIterator[FakeModels]:
    fake = FakeModels()
    await fake.start()
    try:
        yield fake
    finally:
        await fake.stop()


async def _ask_jev(models: FakeModels, goal: str) -> None:
    """Ask Jev for its next operation on a run whose goal names goal."""
    question: dict[str, Any] = {
        "instructions": goal,
        "criteria": {"CLICK": "click", "BLOCKED": "blocked"},
    }
    async with httpx.AsyncClient() as client:
        await client.post(
            f"http://127.0.0.1:{models.port}/api/alpha/decisions",
            json={"questions": {"operation": question}},
        )


async def _unscripted_request(models: FakeModels) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(f"{models.base_url}/chat/completions", json={"messages": []})


async def test_an_earlier_scenarios_error_is_not_the_next_scenarios(models: FakeModels) -> None:
    models.begin_scenario()
    models.script("run-earlier", agent=[])
    await _ask_jev(models, "run-earlier")
    await _unscripted_request(models)
    assert len(models.errors) == 2

    models.begin_scenario()

    assert models.errors == []


async def test_an_earlier_scenarios_run_failing_late_is_not_the_next_scenarios(
    models: FakeModels,
) -> None:
    models.begin_scenario()
    models.script("run-lingering", agent=[])
    models.begin_scenario()
    models.script("run-current", agent=[])

    await _ask_jev(models, "run-lingering")
    assert models.errors == []
    await _ask_jev(models, "run-current")
    assert models.errors == ["run-current: Jev was asked past its script"]
