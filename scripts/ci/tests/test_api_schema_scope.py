"""One scope decides when the generated API contract is re-checked.

`apps/api/openapi.json` and the TypeScript generated from it are build outputs,
so three places have to agree on what can change them: the prek hook that
regenerates on commit, the local lane table, and the CI job that fails on
drift. They did not — the hook and the lane both ignored `apps/api/pyproject.toml`
and `uv.lock`, so a FastAPI or Pydantic bump changed the generated document
with nothing regenerating or checking it.

The source of truth is the lint-mixed:api-schema nx task's inputs: CI gates the
check on it, and the hook's literal regex (prek needs one) is held equal to it
by test_hook_scopes.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib import nx_affected
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
TASK = "lint-mixed:api-schema"
HOOK = "api-types"

# A bump to either one re-generates the document without touching a route.
DEPENDENCY_MANIFESTS = ("apps/api/pyproject.toml", "uv.lock")


def _reaches(path: str) -> bool:
    return TASK in nx_affected.select(["--files", path]).tasks


@pytest.fixture(scope="module")
def hook() -> dict[str, Any]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return next(h for repo in config["repos"] for h in repo.get("hooks", []) if h["id"] == HOOK)


@pytest.mark.parametrize("manifest", DEPENDENCY_MANIFESTS)
def test_a_dependency_manifest_reruns_the_check(manifest: str) -> None:
    """A FastAPI/Pydantic bump changes the generated output with no route edit."""
    assert _reaches(manifest)


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/app/api/v1/endpoints/todos.py",
        "libs/shared/py/analytics/catalog/__init__.py",
        "apps/api/scripts/export_openapi.py",
        "apps/api/scripts/openapi_contract.py",
        "apps/api/openapi.json",
        "libs/shared/ts/src/api/generated/schema.d.ts",
        "scripts/ci/checks.mjs",
    ],
)
def test_a_source_it_generates_from_reruns_the_check(path: str) -> None:
    """The route code, the shared models it imports, the exporter and the artifacts themselves."""
    assert _reaches(path)


@pytest.mark.parametrize("path", ["apps/web/src/app/page.tsx", "docs/release-notes.mdx"])
def test_what_cannot_change_the_document_does_not(path: str) -> None:
    """Scoping is only useful while it still says no."""
    assert not _reaches(path)


def test_the_prek_hook_names_what_it_regenerated(hook: dict[str, Any]) -> None:
    """The hook re-stages build outputs; silence there looks like an unrelated diff."""
    assert "regenerated and staged" in hook["entry"]
    assert "git add" in hook["entry"]
