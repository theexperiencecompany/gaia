"""The world every brief-run test drives run_brief through (tests/briefing_run_world)."""

from collections.abc import Iterator

import pytest
from tests.briefing_run_world import World, run_world


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    yield from run_world(monkeypatch)
