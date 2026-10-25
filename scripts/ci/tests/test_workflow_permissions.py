"""A reusable workflow's jobs get at most the permissions their caller grants.

GitHub rejects the whole calling workflow at startup when a called job asks
for more than the calling job holds. ci.yml's default is `contents: read`, so
a `uses: ./.github/workflows/build.yml` job without its own grant made every
run a startup_failure — no job ran, and no check reported why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from doc_shape import mapping
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LEVEL = {"none": 0, "read": 1, "write": 2}
# The repo's default token is write-all (Settings > Actions), which a workflow
# with no `permissions:` key at any level inherits.
WRITE_ALL = "write-all"


def _load(path: Path) -> dict[str, Any]:
    return mapping(yaml.safe_load(path.read_text()))


def _granted(permissions: object, scope: str) -> int:
    if permissions is None or permissions == WRITE_ALL:
        return LEVEL["write"]
    if permissions == "read-all":
        return LEVEL["read"]
    return LEVEL[str(mapping(permissions).get(scope, "none"))]


def _reusable_calls() -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    calls = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _load(path)
        for name, raw in mapping(workflow["jobs"]).items():
            job = mapping(raw)
            uses = str(job.get("uses", ""))
            if uses.startswith("./.github/workflows/"):
                calls.append((path.name, name, job, workflow))
    return calls


@pytest.mark.parametrize(
    ("caller", "job_name", "job", "workflow"),
    _reusable_calls(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_caller_grants_every_permission_its_called_jobs_ask_for(
    caller: str, job_name: str, job: dict[str, Any], workflow: dict[str, Any]
) -> None:
    granted = job.get("permissions", workflow.get("permissions"))
    called = _load(REPO_ROOT / str(job["uses"]).removeprefix("./"))
    for called_name, raw in mapping(called["jobs"]).items():
        asked = mapping(raw).get("permissions")
        if not isinstance(asked, dict):
            continue
        for scope, level in asked.items():
            assert _granted(granted, scope) >= LEVEL[str(level)], (
                f"{caller}: job '{job_name}' calls {job['uses']}, whose job '{called_name}' "
                f"asks for {scope}: {level}, but the caller grants "
                f"{scope}: {mapping(granted).get(scope, 'none') if isinstance(granted, dict) else granted}"
                " — GitHub fails the whole run at startup"
            )


def test_the_check_finds_the_reusable_calls() -> None:
    assert any(caller == "ci.yml" for caller, *_ in _reusable_calls())
