"""lint-python runs whenever any .py changed, not only when an nx Python project did.

has_python is nx-affected over scope:python projects, and ~160 files under
scripts/, tools/ and docs/ belong to none. Gated on it, every repo-wide check
skipped on a scripts/dev-only change: #1492 added a PLR0913 violation that
its PR, the merge queue and the master push all passed, and only a dispatch
run, which scans everything, went red.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from doc_shape import mapping
import pytest
import yaml

CI_YML = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return mapping(yaml.safe_load(CI_YML.read_text()))


def test_lint_python_gates_on_changed_python_sources(workflow: dict[str, Any]) -> None:
    steps = workflow["jobs"]["lint-python"]["steps"]
    gated = [s for s in steps if "has_python" in str(s.get("if", ""))]
    assert gated, "lint-python no longer gates any step on Python changes — is this test stale?"
    project_gated = [
        s.get("name") or s.get("uses")
        for s in gated
        if "outputs.has_python ==" in s["if"] and "has_python_sources" not in s["if"]
    ]
    assert not project_gated, (
        "These lint-python steps skip Python outside nx projects; gate them on "
        f"needs.detect.outputs.has_python_sources instead: {project_gated}"
    )


def test_detect_exports_the_python_sources_signal(workflow: dict[str, Any]) -> None:
    outputs = workflow["jobs"]["detect"]["outputs"]
    assert outputs["has_python_sources"] == "${{ steps.affected.outputs.has_python_sources }}"
