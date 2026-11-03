"""The PR and merge-queue events the CI workflows answer to.

Every lane scopes itself to the PR's base — `nx affected`, `changes.sh files`,
the mutation matrix's line ranges — and `edited` is the ONLY event a retarget
fires. A PR restacked from master onto the branch it is really stacked on kept
every master-scoped verdict until somebody pushed: PR #1202 mutated 119 modules
for a diff of 11 that way.

But ci.yml must not run on `edited` itself: a run creates every job's check
row, so a title or body edit replaced the commit's real rows with "Skipped".
pr-title.yml runs on `edited` anyway (the title check), so it carries the
retarget: one step, guarded on `github.event.changes.base`, that re-runs the
head's CI run through `runner.py rescope`.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from doc_shape import mapping
from lib import nx_affected
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The job every other job in ci.yml is downstream of.
FIRST_JOB = "select-runner"

# Present in the payload only when the edit moved the base.
BASE_CHANGE_GUARD = "github.event.changes.base"


# Keyed by str except `on`, which YAML 1.1 reads as the boolean true.
Workflow = dict[str | bool, Any]


def _load(name: str) -> Workflow:
    doc = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(doc, dict), f"{name} is not a mapping: {doc!r:.200}"
    return doc


@pytest.fixture(scope="module")
def workflow() -> Workflow:
    return _load("ci.yml")


@pytest.fixture(scope="module")
def title_workflow() -> Workflow:
    return _load("pr-title.yml")


def _triggers(workflow: Workflow) -> dict[str, Any]:
    return mapping(workflow[True] if True in workflow else workflow["on"])


def test_ci_never_runs_on_a_pr_edit(workflow: Workflow) -> None:
    # No `types` keeps GitHub's defaults (opened, synchronize, reopened).
    pull_request = _triggers(workflow)["pull_request"]

    assert pull_request is None or "types" not in pull_request, (
        "ci.yml names pull_request types; with `edited` in them a body edit "
        "replaces every job row of the head commit with Skipped"
    )


def test_the_title_check_runs_on_every_pr_event_and_the_merge_queue(
    title_workflow: Workflow,
) -> None:
    triggers = _triggers(title_workflow)
    assert set(mapping(triggers["pull_request"])["types"]) == {
        "opened",
        "edited",
        "synchronize",
        "reopened",
    }
    # A required check absent from a merge group's checks holds the queue forever.
    assert "merge_group" in triggers
    (job,) = mapping(title_workflow["jobs"]).values()
    assert job["name"] == "Validate PR Title"
    assert "if" not in job, "a job-level if would leave a stale Skipped row"


def test_a_retarget_re_runs_ci_and_nothing_else_does(title_workflow: Workflow) -> None:
    (job,) = mapping(title_workflow["jobs"]).values()
    (step,) = [s for s in job["steps"] if "runner.py rescope" in str(s.get("run", ""))]

    assert step["run"].endswith("rescope ci.yml")
    assert "edited" in step["if"] and BASE_CHANGE_GUARD in step["if"]
    assert job["permissions"]["actions"] == "write"


def test_no_ci_job_special_cases_an_edit(workflow: Workflow) -> None:
    for name, job in mapping(workflow["jobs"]).items():
        assert BASE_CHANGE_GUARD not in str(job.get("if", "")), name
    assert "edited" not in str(workflow["concurrency"]["group"])


def test_the_lanes_that_run_on_skipped_ancestors_still_need_their_runner(
    workflow: Workflow,
) -> None:
    # `!cancelled()` also means "run when an ancestor FAILED or SKIPPED". A job
    # with that condition whose `runs-on` is
    # `fromJSON(needs.select-runner.outputs.<pool>)` gets an empty string once
    # select-runner did not succeed, and fails on the fromJSON — red for a reason
    # unrelated to what it checks.
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


def test_the_gate_reports_on_a_merge_group(workflow: Workflow) -> None:
    # A required check: the gate runs for every event. The title check's half
    # lives in pr-title.yml (test above).
    jobs = workflow["jobs"]
    assert "always()" in jobs["quality-gate"]["if"]
    assert jobs["quality-gate"]["name"] == "quality-gate"


def test_a_pr_push_runs_only_the_fast_tier(workflow: Workflow) -> None:
    # The full-tier jobs never start on a PR push: docker-image gates on detect's
    # tier, and python-audit's and scan's checks name the events they run on.
    jobs = workflow["jobs"]
    assert "needs.detect.outputs.tier == 'full'" in jobs["docker-image"]["if"]
    full_tier = [c for c in nx_affected.checks().values() if c.job in ("python-audit", "scan")]
    assert {c.check for c in full_tier} == {"import-cost", "pip-audit", "semgrep", "trivy"}
    for check in full_tier:
        assert not check.runs_on("pull_request", None), check.task
        assert check.runs_on("merge_group", None), check.task
    for name in ("python-audit", "scan"):
        assert f"contains(fromJSON(needs.detect.outputs.jobs), '{name}')" in jobs[name]["if"]
    # Mutation is in both tiers: a survivor found only in the queue ejects the
    # group and costs a fix round.
    (plan,) = [s for s in jobs["detect"]["steps"] if s.get("id") == "plan"]
    assert "tier" not in plan["if"]
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
    assert "'ci:gitleaks'" in str(steps[0]["if"])
    gitleaks = nx_affected.checks()["ci:gitleaks"]
    assert gitleaks.events == ("pull_request", "push"), (
        "an exclusion list lets workflow_dispatch through"
    )


REPO = "theexperiencecompany/gaia"
# (event, actor, PR head repo, whether statuses are posted)
POSTING = [
    ("pull_request", "aryan", REPO, True),
    ("merge_group", "github-merge-queue[bot]", "", True),
    ("push", "aryan", "", True),
    ("workflow_dispatch", "aryan", "", False),
    ("pull_request", "someone", "fork/gaia", False),
    ("pull_request", "dependabot[bot]", REPO, False),
]


def _evaluate(expression: str, event: str, actor: str, head_repo: str) -> object:
    """Evaluate the NO_POST expression; Python's and/or treat '' as falsy, as Actions does."""
    body = expression.strip().removeprefix("${{").removesuffix("}}")
    body = re.sub(
        r"contains\(fromJSON\('(\[[^']*\])'\), github\.event_name\)",
        lambda m: f"(github_event_name in {m.group(1)})",
        body,
    )
    for ref, value in {
        "github.event.pull_request.head.repo.full_name": head_repo,
        "github.repository": REPO,
        "github.event_name": event,
        "github.actor": actor,
    }.items():
        body = body.replace(ref, repr(value))
    body = body.replace("github_event_name", repr(event))
    body = body.replace("&&", " and ").replace("||", " or ").replace("!(", " not (")
    return eval(body)  # noqa: S307 - a workflow expression this repo wrote, over fixed literals


def test_a_dispatch_never_posts_per_check_statuses(workflow: Workflow) -> None:
    """A dispatch shares its sha with an open PR's head and would overwrite that PR's `ci / <area> / <check>` statuses."""
    posts = [
        mapping(step)
        for job in mapping(workflow["jobs"]).values()
        for step in mapping(job).get("steps", [])
        if "verdict.py post-statuses" in str(mapping(step).get("run", ""))
    ]
    assert posts, "found no post-statuses step"
    for name, job in mapping(workflow["jobs"]).items():
        if not any(
            "verdict.py post-statuses" in str(mapping(s).get("run", ""))
            for s in job.get("steps", [])
        ):
            continue
        no_post = str(mapping(job["env"])["NO_POST"])
        for event, actor, head_repo, posts_here in POSTING:
            got = _evaluate(no_post, event, actor, head_repo)
            assert got == ("" if posts_here else "--no-post"), (name, event, actor, head_repo, got)
    for step in posts:
        assert str(step["run"]).endswith(" $NO_POST"), step["name"]
