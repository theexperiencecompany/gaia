"""A local composite action can only see what a composite action is given.

Two failures cost a full CI run each, and both are invisible in review because
the YAML is well-formed and nothing parses it until a runner does.

1. A composite has NO `matrix`, `needs`, `strategy` or `job` context — only
   `inputs`, `github`, `env`, `runner` and `steps`. Anything matrix-dependent
   must be an INPUT the caller fills from its own matrix. The runner rejects
   the whole action at parse time: `Unrecognized named-value: 'matrix'`, on
   EVERY job that uses it. Note the expression does not have to be in a step —
   an `${{ }}` inside an input's `description` is template-parsed too, which is
   exactly how this shipped: the description held a usage example.

2. A local composite is a path in the checked-out tree. A job that never checks
   out, or checks out a DIFFERENT revision, cannot see one this branch adds:
   `Can't find 'action.yml' ... Did you forget to run actions/checkout`. The
   gate workflows' `select-runner` deliberately pins its checkout to the
   default branch (it handles a PAT, so it must not run PR-authored code), so
   it can only ever use composites that already exist there.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIONS_DIR = REPO_ROOT / ".github" / "actions"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

EXPRESSION = re.compile(r"\$\{\{(.+?)\}\}", re.DOTALL)
# The four contexts a composite does not have. Word-boundary prefixed so a
# step output named `job_matrix` does not read as the `matrix` context.
FORBIDDEN_CONTEXT = re.compile(r"(?<![\w.-])(matrix|needs|strategy|job)\s*\.")
LOCAL_COMPOSITE = re.compile(r"^\./\.github/actions/")


def _every_string(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _every_string(v)]
    if isinstance(node, list):
        return [s for v in node for s in _every_string(v)]
    return []


def _workflows() -> list[tuple[str, dict[str, Any]]]:
    return [(p.name, yaml.safe_load(p.read_text())) for p in sorted(WORKFLOWS_DIR.glob("*.yml"))]


@pytest.mark.parametrize(
    "action", sorted(ACTIONS_DIR.glob("*/action.yml")), ids=lambda p: p.parent.name
)
def test_a_composite_never_reads_a_context_it_does_not_have(action: Path) -> None:
    loaded = yaml.safe_load(action.read_text())
    if loaded.get("runs", {}).get("using") != "composite":
        pytest.skip(f"{action.parent.name} is not a composite action")

    offenders = [
        expression.strip()
        for text in _every_string(loaded)
        for expression in EXPRESSION.findall(text)
        if FORBIDDEN_CONTEXT.search(expression)
    ]
    assert not offenders, (
        f"{action.parent.name}/action.yml reads a context a composite does not have: {offenders}. "
        "The runner rejects the whole action at parse time, on every job that uses it. "
        "Make it an input the caller fills from its own matrix — and note that an "
        "${{ }} inside a `description` is parsed too, so write examples without it."
    )


def _jobs_using_local_composites() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (filename, name, job)
        for filename, workflow in _workflows()
        for name, job in workflow.get("jobs", {}).items()
        if any(LOCAL_COMPOSITE.match(str(s.get("uses", ""))) for s in job.get("steps", []))
    ]


def test_a_local_composite_needs_a_checkout_before_it() -> None:
    # It is a path in the working tree, not something the runner can fetch.
    for filename, name, job in _jobs_using_local_composites():
        steps = job["steps"]
        first_composite = next(
            i for i, s in enumerate(steps) if LOCAL_COMPOSITE.match(str(s.get("uses", "")))
        )
        checkouts = [
            i
            for i, s in enumerate(steps[:first_composite])
            if "actions/checkout" in str(s.get("uses", ""))
        ]
        assert checkouts, (
            f"{filename}: job '{name}' runs {steps[first_composite]['uses']} with no "
            "actions/checkout before it — the runner cannot find the action's directory"
        )


def test_a_job_pinned_to_another_revision_only_uses_composites_that_exist_there() -> None:
    # `select-runner` checks out the DEFAULT BRANCH on purpose (it handles a
    # PAT and must not run PR-authored code), so a composite this branch adds
    # does not exist in its tree. That is not a bug to fix in the job — it is a
    # constraint the caller has to respect.
    default_branch = "origin/master"
    if subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", default_branch],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    ).returncode:
        pytest.skip(f"{default_branch} is not available in this checkout")

    for filename, name, job in _jobs_using_local_composites():
        pinned = [
            s
            for s in job["steps"]
            if "actions/checkout" in str(s.get("uses", "")) and (s.get("with") or {}).get("ref")
        ]
        if not pinned:
            continue
        for step in job["steps"]:
            uses = str(step.get("uses", ""))
            if not LOCAL_COMPOSITE.match(uses):
                continue
            path = f"{uses.removeprefix('./')}/action.yml"
            exists = not subprocess.run(
                ["git", "cat-file", "-e", f"{default_branch}:{path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            ).returncode
            assert exists, (
                f"{filename}: job '{name}' pins its checkout to another revision but uses "
                f"{uses}, which does not exist on {default_branch}. That job's runner will "
                "fail with \"Can't find 'action.yml'\". Either the job is result-only, or the "
                "action has to land on the default branch first."
            )
