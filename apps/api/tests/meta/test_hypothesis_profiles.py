"""Every Hypothesis profile CI selects draws the same examples on every run."""

from __future__ import annotations

from pathlib import Path
import re

from hypothesis import settings
import pytest

CI_WORKFLOW = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"


def _profiles_ci_selects() -> set[str]:
    lines = [ln for ln in CI_WORKFLOW.read_text().splitlines() if "HYPOTHESIS_PROFILE:" in ln]
    return {
        name
        for ln in lines
        for name in re.findall(r"'([a-z-]+)'", ln) or [ln.split(":", 1)[1].strip()]
    }


@pytest.mark.parametrize("name", sorted(_profiles_ci_selects()))
def test_a_ci_profile_is_derandomized_and_keeps_no_example_database(name: str) -> None:
    """Random examples let master go red on the code the merge queue passed."""
    profile = settings.get_profile(name)
    assert profile.derandomize
    assert profile.database is None
