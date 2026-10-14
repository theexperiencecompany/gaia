"""One scope decides when the generated API contract is re-checked.

`apps/api/openapi.json` and the TypeScript generated from it are build outputs,
so three places have to agree on what can change them: the prek hook that
regenerates on commit, the local lane table, and the CI job that fails on
drift. They did not — the hook and the lane both ignored `apps/api/pyproject.toml`
and `uv.lock`, so a FastAPI or Pydantic bump changed the generated document
with nothing regenerating or checking it, and CI's api-schema lane keyed off
nx-affected, which a manifest-only bump need not move either.

The lane table is the source of truth. The hook copies the regex (prek needs a
literal) and this test fails if the copy drifts; the workflow greps it straight
out of the file.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LANES = REPO_ROOT / "scripts" / "dev" / "verify-lanes.json"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "code-quality.yml"
LANE = "api-schema"
HOOK = "api-types"

# A bump to either one re-generates the document without touching a route.
DEPENDENCY_MANIFESTS = ("apps/api/pyproject.toml", "uv.lock")


@pytest.fixture(scope="module")
def scope() -> str:
    lanes = json.loads(LANES.read_text(encoding="utf-8"))["lanes"]
    return next(lane["scope"] for lane in lanes if lane["name"] == LANE)


@pytest.fixture(scope="module")
def hook() -> dict[str, Any]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return next(h for repo in config["repos"] for h in repo.get("hooks", []) if h["id"] == HOOK)


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize("manifest", DEPENDENCY_MANIFESTS)
def test_the_scope_covers_the_dependency_manifests(scope: str, manifest: str) -> None:
    """A FastAPI/Pydantic bump changes the generated output with no route edit."""
    assert re.search(scope, manifest), f"{manifest} is not in the {LANE} scope: {scope}"


def test_the_scope_covers_the_sources_it_generates_from(scope: str) -> None:
    """The route code, the exporter and the artifacts themselves."""
    for path in (
        "apps/api/app/api/v1/endpoints/todos.py",
        "apps/api/scripts/export_openapi.py",
        "apps/api/openapi.json",
        "libs/shared/ts/src/api/generated/schema.d.ts",
        "scripts/ci/checks.mjs",
    ):
        assert re.search(scope, path), f"{path} is not in the {LANE} scope"


def test_the_scope_skips_what_cannot_change_the_document(scope: str) -> None:
    """Scoping is only useful while it still says no."""
    for path in ("apps/web/src/app/page.tsx", "docs/release-notes.mdx"):
        assert not re.search(scope, path), f"{path} should not trigger the {LANE} lane"


def test_the_prek_hook_carries_the_same_scope(scope: str, hook: dict[str, Any]) -> None:
    """Compare the literal copy, since prek cannot derive the scope."""
    assert hook["files"] == scope, (
        f"the {HOOK} hook's files: drifted from the {LANE} lane's scope in "
        f"{LANES.name} — copy it across:\n  hook: {hook['files']}\n  lane: {scope}"
    )


def test_the_prek_hook_names_what_it_regenerated(hook: dict[str, Any]) -> None:
    """The hook re-stages build outputs; silence there looks like an unrelated diff."""
    assert "regenerated and staged" in hook["entry"]
    assert "git add" in hook["entry"]


def test_the_ci_lane_reads_the_scope_from_the_lane_table(workflow: dict[str, Any]) -> None:
    """Grepping the same file is what keeps CI from becoming a fourth opinion."""
    detect = next(
        step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "detect"
    )
    assert "verify-lanes.json" in detect["run"]
    assert f"'{LANE}'" in detect["run"]
    assert "has_api_schema=" in detect["run"]
    assert workflow["jobs"]["changes"]["outputs"]["has_api_schema"]


def test_the_api_schema_job_is_gated_on_that_signal(workflow: dict[str, Any]) -> None:
    """Without this the lane still rides on nx-affected alone."""
    condition = workflow["jobs"][LANE]["if"]
    assert "needs.changes.outputs.has_api_schema == 'true'" in condition
