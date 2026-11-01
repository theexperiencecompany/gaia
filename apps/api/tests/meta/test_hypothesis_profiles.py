"""The Hypothesis profiles CI selects: the gate draws a fixed set, master a seeded fresh one."""

from __future__ import annotations

from pathlib import Path
import re

from hypothesis import settings
import pytest

CI_WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"
PYTEST_SH = Path(__file__).resolve().parents[4] / "scripts" / "ci" / "pytest.sh"


def _profiles_ci_selects() -> set[str]:
    lines = [ln for ln in CI_WORKFLOW.read_text().splitlines() if "HYPOTHESIS_PROFILE:" in ln]
    return {
        name
        for ln in lines
        for name in re.findall(r"'([a-z-]+)'", ln) or [ln.split(":", 1)[1].strip()]
    }


@pytest.mark.parametrize("name", sorted(_profiles_ci_selects()))
def test_a_ci_profile_keeps_no_example_database(name: str) -> None:
    """A database replays whatever a runner happened to keep, so two runs of one commit differ."""
    assert settings.get_profile(name).database is None


def test_the_gating_profile_is_derandomized() -> None:
    """The merge queue must reproduce the PR's verdict; random examples let it go red on passed code."""
    assert settings.get_profile("ci").derandomize


def test_master_explores_new_examples_seeded_from_the_commit() -> None:
    """A derandomized master drew the same 200 examples per test forever, so it found nothing new."""
    assert not settings.get_profile("ci-full").derandomize
    assert "--hypothesis-seed=" in PYTEST_SH.read_text()
