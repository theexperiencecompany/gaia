"""One resolved base per run, handed to every lane that scopes a diff.

For a PR in a native GitHub stack, the `pull_request` event payload carries the
stack's TRUNK in base.ref rather than the PR's parent. Measured 2026-09-11 on
#1161/#1202/#1175: `gh api pulls/N --jq .base.ref` named the parent for each,
while `github.base_ref` inside every job said `master` — from the morning's
`gh stack link` onward. Every diff-scoped lane reads that value, so all three
PRs linted, type-checked, duplicate-scanned and mutated the whole stack:
#1175's mutation plan took 119 modules for a diff of one, and its
regression-proof lane demanded proof for seven tests it had not added.

The fix is one resolver per run — `changes.sh base`, in the job that already
detects changes — published as a job output and passed down as $GAIA_PR_BASE.
These tests pin both halves: the resolution happens, and every lane downstream
of it actually receives the answer. A lane that silently keeps reading
`github.base_ref` is back to scoping against the bottom of the stack, and
nothing about its output says so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The job each workflow resolves the base in: the first one that inspects the
# diff, and the one every scoped lane already depends on.
DETECTOR = {"code-quality.yml": "changes", "main.yml": "detect"}
RESOLVER = "scripts/ci/changes.sh base"
BASE_ENV = "GAIA_PR_BASE"

# Jobs that legitimately never scope a diff: runner routing, the resolver
# itself, the gate that only reads results, and the master-only publish path.
UNSCOPED = {
    "select-runner",
    "select-runner-services",
    "runner-watchdog",
    "probe",
    "changes",
    "detect",
    "quality-gate",
    "build-images",
    "trigger-build",
}


@pytest.fixture(scope="module", params=sorted(DETECTOR))
def named_workflow(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any]]:
    return request.param, yaml.safe_load((WORKFLOWS / request.param).read_text())


def test_the_run_resolves_the_real_base_once(named_workflow: tuple[str, dict[str, Any]]) -> None:
    name, workflow = named_workflow
    steps = workflow["jobs"][DETECTOR[name]]["steps"]

    resolver = [step for step in steps if RESOLVER in str(step.get("run", ""))]
    assert resolver, f"{name}: {DETECTOR[name]} never runs `{RESOLVER}`"
    # The API call needs a token and the PR number; without either it silently
    # falls back to the payload, which is the bug.
    env = resolver[0].get("env", {})
    assert "GITHUB_TOKEN" in env
    assert "pull_request.number" in str(env.get("PR_NUMBER", ""))


def test_the_resolved_base_is_published_as_a_job_output(
    named_workflow: tuple[str, dict[str, Any]],
) -> None:
    name, workflow = named_workflow
    outputs = workflow["jobs"][DETECTOR[name]].get("outputs", {})

    assert "base_ref" in outputs, (
        f"{name}: {DETECTOR[name]} resolves the base but does not publish it — "
        "no downstream job can read it"
    )


def test_every_scoping_job_receives_the_resolved_base(
    named_workflow: tuple[str, dict[str, Any]],
) -> None:
    name, workflow = named_workflow
    detector = DETECTOR[name]

    for job, spec in workflow["jobs"].items():
        if job in UNSCOPED:
            continue
        env = str(spec.get("env", {}))
        assert BASE_ENV in env, (
            f"{name}: job '{job}' has no {BASE_ENV} — anything it scopes will "
            "diff against the stack's trunk instead of this PR's parent"
        )
        assert f"needs.{detector}.outputs.base_ref" in env, (
            f"{name}: job '{job}' sets {BASE_ENV} from something other than the "
            f"{detector} job's resolved output"
        )


def test_no_scoping_job_still_reads_the_raw_payload(
    named_workflow: tuple[str, dict[str, Any]],
) -> None:
    # `github.base_ref` is the value that lies. It may appear in a comment, but
    # not as an input to a step that scopes anything: that is precisely the
    # regression this whole change exists to prevent, and it reads as a
    # perfectly ordinary line.
    name, workflow = named_workflow

    for job, spec in workflow["jobs"].items():
        for step in spec.get("steps", []):
            env = step.get("env", {})
            offenders = [key for key, value in env.items() if "github.base_ref" in str(value)]
            assert not offenders, (
                f"{name}: step {step.get('name') or step.get('uses')} in '{job}' passes "
                f"github.base_ref as {offenders} — on a stacked PR that names the "
                f"stack's trunk. Use needs.{DETECTOR[name]}.outputs.base_ref."
            )


def test_the_regression_proof_lane_proves_against_this_prs_base() -> None:
    # The lane re-runs a PR's new tests on its base and requires them to FAIL
    # there. Against the stack's trunk it charges a stacked PR with every test
    # the PRs below it added (7, on #1175, which added none) — and a test that
    # passes on the parent because the parent already carries its fix fails the
    # lane for being correct.
    workflow = yaml.safe_load((WORKFLOWS / "main.yml").read_text())
    steps = workflow["jobs"]["regression-proof"]["steps"]
    run = next(s["run"] for s in steps if "pytest.sh regression-proof" in str(s.get("run", "")))

    assert BASE_ENV in run, f"regression-proof still proves against a fixed base: {run!r}"
