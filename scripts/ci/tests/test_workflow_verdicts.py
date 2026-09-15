"""Every gated lane reports through the verdict contract, and the gate reads it.

A lane's verdict used to be the last hundred lines of a 20k-190k line log, and
whether it produced an `::error file=,line=` annotation at all was per-lane
folklore: `python-static` did, `test-python` and `regression-proof` did not.
The contract (scripts/ci/verdict.py) fixes that only for as long as every gated
job actually goes through it — and a job can stop doing so by deleting four
lines of YAML, which is invisible in review and produces no failure anywhere.

So: for both gate workflows, every job the gate NEEDS uploads its verdicts, and
the gate expects exactly that set. A lane can then only go quiet by editing
this list, which a reviewer sees.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = {
    "main.yml": REPO_ROOT / ".github" / "workflows" / "main.yml",
    "code-quality.yml": REPO_ROOT / ".github" / "workflows" / "code-quality.yml",
}
UPLOAD_VERDICT = "./.github/actions/upload-verdict"
# A lane that cannot run a local composite at all — no checkout, or a checkout
# pinned to another revision. It is declared, never silently dropped: the gate
# still fails on its job result, it just has no verdict artifact to wait for.
RESULT_ONLY = "result-only"


@pytest.fixture(scope="module", params=sorted(WORKFLOWS))
def workflow(request: pytest.FixtureRequest) -> dict[str, Any]:
    return yaml.safe_load(WORKFLOWS[request.param].read_text())


def _gate(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]["quality-gate"]


def _gated_jobs(workflow: dict[str, Any]) -> list[str]:
    # A reusable-workflow caller (`uses:`) has no steps of its own to add one
    # to; nothing in either gate's needs is one today, and this keeps the
    # failure message about the real case if one ever is.
    return [j for j in _gate(workflow)["needs"] if "steps" in workflow["jobs"][j]]


def _job_name(entry: str) -> str:
    """Return the `needs` entry one `--expect` entry enforces.

    `<job>[@<family>][*<planned members>][=<result>]` — everything after the job
    name says how it is satisfied, not which job it is.
    """
    return entry.partition("=")[0].partition("*")[0].partition("@")[0].strip()


def _result_only(workflow: dict[str, Any]) -> set[str]:
    return {
        _job_name(entry) for entry in _expect_arg(workflow).split(",") if f"@{RESULT_ONLY}" in entry
    }


def _reporting_jobs(workflow: dict[str, Any]) -> list[str]:
    declared = _result_only(workflow)
    return [j for j in _gated_jobs(workflow) if j not in declared]


def _expect_arg(workflow: dict[str, Any]) -> str:
    for step in _gate(workflow)["steps"]:
        env = step.get("env", {})
        if "EXPECT" in env:
            return str(env["EXPECT"])
    raise AssertionError("the quality-gate job passes no EXPECT to `verdict.py consolidate`")


def test_every_gated_job_uploads_its_verdict(workflow: dict[str, Any]) -> None:
    for name in _reporting_jobs(workflow):
        steps = [s for s in workflow["jobs"][name]["steps"] if s.get("uses") == UPLOAD_VERDICT]
        assert steps, (
            f"job '{name}' is in quality-gate.needs but never runs {UPLOAD_VERDICT} — "
            "its verdict cannot reach the gate, and the gate will read it as NO VERDICT"
        )


def test_the_upload_runs_even_when_the_lane_failed(workflow: dict[str, Any]) -> None:
    # The whole point is the red lane. Without always() the upload is skipped
    # exactly when its findings matter.
    for name in _reporting_jobs(workflow):
        for step in workflow["jobs"][name]["steps"]:
            if step.get("uses") == UPLOAD_VERDICT:
                assert "always()" in str(step.get("if", "")), (
                    f"job '{name}': the verdict upload must be `if: always()` — "
                    "a failed lane is the one whose verdict is worth reading"
                )


def test_verdict_artifact_names_are_unique(workflow: dict[str, Any]) -> None:
    # upload-artifact refuses a duplicate name, so a matrix job that does not
    # fold its matrix value into the name fails its own upload — after the
    # lane has already passed, where nobody looks.
    names: list[str] = []
    for name in _reporting_jobs(workflow):
        job = workflow["jobs"][name]
        for step in job["steps"]:
            if step.get("uses") != UPLOAD_VERDICT:
                continue
            given = str(step["with"]["name"])
            if "strategy" in job:
                assert "matrix." in given or "strategy.job-index" in given, (
                    f"job '{name}' is a matrix job: its verdict artifact name {given!r} "
                    "must include the matrix value or the shards collide"
                )
            names.append(given)
    assert len(names) == len(set(names)), f"duplicate verdict artifact names: {names}"


def test_the_gate_consolidates_instead_of_printing_results(workflow: dict[str, Any]) -> None:
    runs = " ".join(str(s.get("run", "")) for s in _gate(workflow)["steps"])
    assert "verdict.py consolidate" in runs, (
        "the quality gate must reach its verdict through `verdict.py consolidate` — "
        "a hand-rolled result loop cannot tell a timeout from a failure, and sees "
        "nothing a lane actually found"
    )


def test_the_gate_expects_exactly_the_lanes_it_needs(workflow: dict[str, Any]) -> None:
    # `<job>@<family>` — the job name is what has to match `needs`; the family
    # is which lane ids satisfy it (see `verdict.py consolidate --help`).
    expected = {_job_name(entry) for entry in _expect_arg(workflow).split(",")}
    expected.discard("")
    assert expected == set(_gate(workflow)["needs"]), (
        "quality-gate's --expect list and its needs list have drifted; a lane missing "
        "from --expect can stop reporting without the gate noticing"
    )


def test_the_gate_passes_each_lanes_job_result(workflow: dict[str, Any]) -> None:
    # Without the result, consolidate cannot tell the two silences apart: a
    # SKIPPED lane legitimately writes no verdict (the changes job proved its
    # language untouched), while a successful lane that wrote none has lost its
    # reporting. Conflating them either reds every TS-only PR or hides the bug
    # this whole contract exists to catch.
    for entry in _expect_arg(workflow).split(","):
        result = entry.strip().partition("=")[2]
        lane = _job_name(entry)
        if not lane:
            continue
        assert re.fullmatch(r"\$\{\{\s*needs\." + re.escape(lane) + r"\.result\s*\}\}", result), (
            f"lane '{lane}' in --expect carries {result!r}, not its needs.<job>.result"
        )


def test_a_reporting_job_can_actually_reach_the_composite(workflow: dict[str, Any]) -> None:
    # The composite is a path in the checked-out tree. A job with no checkout,
    # or one pinned to another revision, cannot see it — `select-runner` pins to
    # the default branch on purpose and `probe` never checks out at all. Such a
    # job must be declared result-only rather than handed a step that cannot run.
    for name in _reporting_jobs(workflow):
        steps = workflow["jobs"][name]["steps"]
        checkouts = [s for s in steps if "actions/checkout" in str(s.get("uses", ""))]
        assert checkouts, (
            f"job '{name}' has no checkout, so it cannot run {UPLOAD_VERDICT}. "
            f"Declare it `{name}@{RESULT_ONLY}=...` in the gate's EXPECT instead."
        )
        assert not any((c.get("with") or {}).get("ref") for c in checkouts), (
            f"job '{name}' pins its checkout to another revision, so a composite this "
            f"branch adds does not exist in its tree. Declare it `{name}@{RESULT_ONLY}=...`."
        )


def test_a_result_only_lane_still_fails_the_gate_on_its_job_result(
    workflow: dict[str, Any],
) -> None:
    # Result-only means "no verdict expected", never "not enforced". The job
    # result still travels, so `verdict.py consolidate` can still red the gate.
    for entry in _expect_arg(workflow).split(","):
        if f"@{RESULT_ONLY}" not in entry:
            continue
        assert "=" in entry, f"result-only entry {entry!r} carries no job result — it is unenforced"


def test_every_upload_passes_the_calling_jobs_status(workflow: dict[str, Any]) -> None:
    # `job.status` can only be read by the CALLER. Inside a composite,
    # success()/failure()/cancelled() evaluate that action's own prior steps, so
    # the composite cannot work out whether its job failed — it always looked
    # successful. Run 34584038269's mutation shard 5/6 failed in
    # `setup-python-test-env` and uploaded {"status": "pass"} because of it, and
    # a false pass is the one outcome this whole contract exists to prevent.
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if step.get("uses") != UPLOAD_VERDICT:
                continue
            given = str(step.get("with", {}).get("status", ""))
            assert given.replace(" ", "") == "${{job.status}}", (
                f"job '{name}' calls {UPLOAD_VERDICT} with status={given!r}. It must pass "
                "`${{ job.status }}` — the composite cannot see the job's status itself, "
                "and without it every lane reports `pass`."
            )


# The checkout is never the verdict directory: a self-hosted workspace persists
# between jobs, so verdicts left in the tree get uploaded by the NEXT job to
# land on that runner, and anything else in the job that writes there rides
# along. `runner.temp` is per-job and GitHub wipes it.
CHECKOUT_DIR = "verify-logs/verdicts"


def test_the_gate_reads_verdicts_from_the_runners_own_temp_dir(workflow: dict[str, Any]) -> None:
    steps = _gate(workflow)["steps"]
    download = [s for s in steps if "download-artifact" in str(s.get("uses", ""))]
    assert download, "the gate downloads no verdict artifacts"
    for step in download:
        assert "runner.temp" in str(step["with"]["path"]), (
            f"the gate downloads verdicts to {step['with']['path']!r}; that must be "
            "runner.temp, the same per-job dir every lane uploaded from"
        )
    consolidate = [s for s in steps if "verdict.py consolidate" in str(s.get("run", ""))]
    (step,) = consolidate
    assert CHECKOUT_DIR not in str(step["run"]), (
        "the gate consolidates the CHECKOUT's verdict tree — it would read whatever "
        "a previous job on this runner left behind"
    )


def test_no_workflow_env_block_reads_a_context_it_cannot_see(workflow: dict[str, Any]) -> None:
    # `runner` is NOT available in a workflow-level or job-level `env:` — only
    # in a step's. Putting `${{ runner.temp }}` there fails the whole run at
    # parse time, the same way `matrix` in a composite did. This is the trap
    # that decided the shape of the fix: the location is resolved in the step
    # (and in verdict.py from RUNNER_TEMP), never in a shared env block.
    blocks = [("workflow", workflow.get("env", {}))]
    blocks += [(name, job.get("env", {})) for name, job in workflow["jobs"].items()]
    for where, block in blocks:
        for key, value in block.items():
            assert "runner." not in str(value), (
                f"{where} env `{key}` reads the runner context, which is not available "
                f"there: {value!r}. Resolve it in a step, or from $RUNNER_TEMP."
            )


def test_the_mutation_family_declares_how_many_shards_were_planned(
    workflow: dict[str, Any],
) -> None:
    # A family is satisfied by its members, and how many members a matrix has is
    # known only at runtime — so without the planned count one surviving shard
    # speaks for every shard that was cancelled before it could upload. The
    # planner already emits it; `*<count>` is how it reaches the gate.
    if "test-mutation" not in _gate(workflow)["needs"]:
        return
    (entry,) = [e for e in _expect_arg(workflow).split(",") if _job_name(e) == "test-mutation"]
    members = entry.partition("=")[0].partition("*")[2]
    assert re.fullmatch(
        r"\$\{\{\s*needs\.test-mutation-plan\.outputs\.count\s*\}\}", members.strip()
    ), (
        f"the mutation entry in --expect declares {members!r} planned members. It must carry "
        "`*${{ needs.test-mutation-plan.outputs.count }}` — the shard count the plan job packed "
        "the diff into, and the only thing that makes a missing shard visible to the gate"
    )


def test_the_mutation_shard_declares_the_namespace_it_owns(workflow: dict[str, Any]) -> None:
    # mutation.sh writes one verdict per MODULE under `mutation/`, not under the
    # shard's own lane, so without this the ownership check would reject every
    # one of them.
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if step.get("uses") != UPLOAD_VERDICT:
                continue
            lane = str(step["with"].get("lane", ""))
            if not lane.startswith("mutation/"):
                continue
            assert step["with"].get("family") == "mutation", (
                f"job '{name}' uploads lane {lane!r} but does not declare "
                "`family: mutation`, so its per-module verdicts read as foreign"
            )


# A required check whose latest run on the head SHA is `skipped` counts as
# PASSING for branch protection. So the gate may never skip: a plain title or
# body edit fires `edited`, the whole lane DAG skips (that part is right — the
# tree did not move), and a gate that skipped with it would overwrite a RED
# verdict on that same SHA with a green tick nobody ran. The gate stays
# `always()` and mirrors what the head SHA's last completed run concluded.
MIRROR_COMMAND = "verdict.py mirror-previous-gate"
CONSOLIDATE_COMMAND = "verdict.py consolidate"
PLAIN_EDIT = ("github.event.action", "edited", "github.event.changes.base")


def _step_with(workflow: dict[str, Any], command: str) -> dict[str, Any]:
    matches = [s for s in _gate(workflow)["steps"] if command in str(s.get("run", ""))]
    assert len(matches) == 1, f"the quality-gate job has {len(matches)} `{command}` steps, want 1"
    return matches[0]


def test_the_gate_never_skips_itself_on_a_pr_edit(workflow: dict[str, Any]) -> None:
    condition = str(_gate(workflow).get("if", ""))

    assert "always()" in condition
    assert "changes.base" not in condition, (
        "quality-gate skips itself on a plain edit. A skipped required check counts as "
        "PASSING, so editing the title of a PR whose last run was RED flips the same head "
        "SHA to mergeable with no completed verdict behind it"
    )


def test_a_plain_edit_mirrors_the_head_shas_last_completed_verdict(
    workflow: dict[str, Any],
) -> None:
    condition = str(_step_with(workflow, MIRROR_COMMAND).get("if", ""))

    for token in PLAIN_EDIT:
        assert token in condition, (
            f"the gate's mirror step is guarded by {condition!r}, which does not read "
            f"{token}: it must run for exactly the edit that skipped every lane"
        )


def test_the_gate_does_not_consolidate_a_run_that_ran_no_lanes(
    workflow: dict[str, Any],
) -> None:
    # The other half: with every lane skipped, `consolidate` has nothing to read
    # — main.yml's list would print "quality-gate: PASSED" having run nothing.
    condition = str(_step_with(workflow, CONSOLIDATE_COMMAND).get("if", ""))

    for token in PLAIN_EDIT:
        assert token in condition, (
            f"the gate consolidates under {condition!r}, which does not read {token}: on a "
            "plain edit every lane is skipped and there is no run to consolidate"
        )
