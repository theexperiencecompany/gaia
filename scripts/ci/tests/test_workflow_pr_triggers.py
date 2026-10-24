"""The PR and merge-queue events the CI workflow answers to.

Every lane scopes itself to the PR's base — `nx affected`,
`changes.sh files`, the mutation matrix's line ranges. GitHub's default
`pull_request` types (opened, synchronize, reopened) do not include `edited`,
and `edited` is the ONLY event a retarget fires. So a PR restacked from master
onto the branch it is really stacked on keeps every master-scoped verdict,
with a green tick, until somebody happens to push: PR #1202 mutated 119
modules for a diff of 11 that way.

The other half of the contract is that the extra event must be nearly free.
`edited` fires for a title or a body change too, and those invalidate nothing,
so the first job of the workflow — the one everything else is downstream of —
carries a guard on `github.event.changes.base`, which the payload carries only
on a retarget.

Both halves are asserted here because either one alone is a bug: without the
trigger the gates go stale, and without the guard every typo fix runs the full
16-core pipeline and prints a PASSED verdict having run nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from doc_shape import mapping
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The job every other job in that workflow is downstream of, so its `if:` is
# the workflow-level condition GitHub does not offer.
FIRST_JOB = "select-runner"

# Present in the payload only when the edit moved the base.
BASE_CHANGE_GUARD = "github.event.changes.base"


# Keyed by str except `on`, which YAML 1.1 reads as the boolean true.
Workflow = dict[str | bool, Any]


@pytest.fixture(scope="module")
def workflow() -> Workflow:
    doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    assert isinstance(doc, dict), f"ci.yml is not a mapping: {doc!r:.200}"
    return doc


def _triggers(workflow: Workflow) -> dict[str, Any]:
    return mapping(workflow[True] if True in workflow else workflow["on"])


def _pull_request(workflow: Workflow) -> dict[str, Any]:
    return mapping(_triggers(workflow)["pull_request"])


def test_a_retarget_re_runs_the_workflow(workflow: Workflow) -> None:
    types = _pull_request(workflow)["types"]

    assert "edited" in types, (
        "pull_request has no `edited` type, so a retargeted PR keeps the "
        "verdicts it earned against its old base until someone pushes"
    )


def test_the_default_events_are_all_still_there(workflow: Workflow) -> None:
    # Naming `types` at all replaces the defaults wholesale: listing only
    # `edited` would silently stop gating pushes, which is the entire lane.
    types = _pull_request(workflow)["types"]

    assert set(types) >= {"opened", "synchronize", "reopened"}


def test_an_edit_that_moved_nothing_skips_the_whole_workflow(
    workflow: Workflow,
) -> None:
    condition = workflow["jobs"][FIRST_JOB].get("if", "")

    assert "edited" in condition and BASE_CHANGE_GUARD in condition, (
        f"{FIRST_JOB} has no base-change guard: every title and body edit now "
        "starts the full pipeline"
    )


def test_the_gate_still_decides_such_an_edit(workflow: Workflow) -> None:
    # The gate is the required check, and the DAG's guard must NOT reach it.
    # Skipping looked like the honest answer for a run that checked nothing,
    # but branch protection counts a skipped required check as PASSING: the
    # edit run's skipped gate became the head SHA's latest verdict, so editing
    # the title of a PR whose lanes had just gone red made it mergeable. The
    # gate runs for every event and mirrors this SHA's last completed verdict
    # instead — the split lives in its steps (test_workflow_verdicts.py).
    condition = workflow["jobs"]["quality-gate"]["if"]

    assert "always()" in condition
    assert BASE_CHANGE_GUARD not in condition


def test_the_lanes_that_run_on_skipped_ancestors_still_need_their_runner(
    workflow: Workflow,
) -> None:
    # `!cancelled()` also means "run when an ancestor SKIPPED". A job with that
    # condition whose `runs-on` is `fromJSON(needs.select-runner.outputs.<pool>)`
    # gets an empty string once the guard above skips select-runner, and fails
    # on the fromJSON — red for a reason unrelated to what it checks.
    #
    # Two conditions survive that: requiring select-runner to have succeeded,
    # or gating on a change-detection OUTPUT, which is likewise empty when the
    # chain skipped. Most lanes have the second already; the ones that check
    # nothing but `!cancelled()` are the ones this pins.
    for name, job in workflow["jobs"].items():
        condition = str(job.get("if", ""))
        if "!cancelled()" not in condition:
            continue
        if f"needs.{FIRST_JOB}.outputs." not in str(job.get("runs-on", "")):
            continue
        assert f"needs.{FIRST_JOB}.result == 'success'" in condition or ".outputs." in condition, (
            f"{name} runs on the selected runner under a bare !cancelled(): "
            "with select-runner skipped its runs-on is an empty fromJSON"
        )


def test_the_merge_queue_runs_the_workflow(workflow: Workflow) -> None:
    # A PR only reaches master through the queue, and the queue waits on the
    # required checks of a `merge_group` run: without the trigger it waits forever.
    assert "merge_group" in _triggers(workflow)


def test_the_gate_and_the_title_check_report_on_a_merge_group(workflow: Workflow) -> None:
    # Both are required checks. The gate runs for every event; the title check
    # SKIPS on a merge group — a skipped required check passes, and the title
    # was validated on the PR before it could be queued — but must not be absent
    # from the run altogether, which is what an event-level filter would do.
    jobs = workflow["jobs"]
    assert "always()" in jobs["quality-gate"]["if"]
    assert jobs["pr-title"]["name"] == "Validate PR Title"
    assert jobs["quality-gate"]["name"] == "quality-gate"


def test_a_pr_push_runs_only_the_fast_tier(workflow: Workflow) -> None:
    # The full-tier jobs gate on detect's tier; a PR push never starts them.
    jobs = workflow["jobs"]
    for name in ("python-audit", "scan", "docker-image"):
        assert "needs.detect.outputs.tier == 'full'" in jobs[name]["if"], name
    (tier,) = [s for s in jobs["detect"]["steps"] if s.get("id") == "tier"]
    assert tier["env"]["TIER"] == "${{ github.event_name == 'pull_request' && 'fast' || 'full' }}"


def test_the_secret_scan_runs_only_on_the_events_that_bring_commits(workflow: Workflow) -> None:
    """Regression for run 40050150344: on a dispatch the action scans ALL history and fails on old findings."""
    steps = [
        mapping(step)
        for job in mapping(workflow["jobs"]).values()
        for step in mapping(job).get("steps", [])
        if "gitleaks/gitleaks-action" in str(mapping(step).get("uses", ""))
    ]
    assert len(steps) == 1
    condition = str(steps[0]["if"])
    assert "github.event_name == 'pull_request'" in condition
    assert "github.event_name == 'push'" in condition
    assert "!=" not in condition.split("&&")[0], "an exclusion list lets workflow_dispatch through"
