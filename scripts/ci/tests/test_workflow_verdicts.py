"""Every gated lane reports through the verdict contract, and the gate reads it.

A lane's verdict used to be the last hundred lines of a 20k-190k line log, and
whether it produced an `::error file=,line=` annotation at all was per-lane
folklore: `python-static` did, `test-python` and `regression-proof` did not.
The contract (scripts/ci/verdict.py) fixes that only for as long as every gated
job actually goes through it — and a job can stop doing so by deleting four
lines of YAML, which is invisible in review and produces no failure anywhere.

So: every job the gate NEEDS uploads its verdicts, and the gate expects exactly
that set. A lane can then only go quiet by editing
this list, which a reviewer sees.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from doc_shape import mapping
import pytest
import verdict
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = {"ci.yml": REPO_ROOT / ".github" / "workflows" / "ci.yml"}
UPLOAD_VERDICT = "./.github/actions/upload-verdict"
# A lane that cannot run a local composite at all — no checkout, or a checkout
# pinned to another revision. It is declared, never silently dropped: the gate
# still fails on its job result, it just has no verdict artifact to wait for.
RESULT_ONLY = "result-only"


@pytest.fixture(scope="module", params=sorted(WORKFLOWS))
def workflow(request: pytest.FixtureRequest) -> dict[str, Any]:
    return mapping(yaml.safe_load(WORKFLOWS[request.param].read_text()))


def _gate(workflow: dict[str, Any]) -> dict[str, Any]:
    return mapping(workflow["jobs"]["quality-gate"])


def _gated_jobs(workflow: dict[str, Any]) -> list[str]:
    # A reusable-workflow caller (`uses:`) has no steps of its own to add one
    # to; nothing in the gate's needs is one today, and this keeps the
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


def _is_partial(step: dict[str, Any]) -> bool:
    return str(step.get("with", {}).get("partial", "")) == "true"


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
    seen_steps: list[object] = []
    for name in _reporting_jobs(workflow):
        job = workflow["jobs"][name]
        # Jobs running one aliased steps list (test-python, test-python-engines)
        # are one lane over disjoint matrices: their names are one template.
        if any(job["steps"] is steps for steps in seen_steps):
            continue
        seen_steps.append(job["steps"])
        for step in job["steps"]:
            if step.get("uses") != UPLOAD_VERDICT or _is_partial(step):
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
        r"\$\{\{\s*needs\.detect\.outputs\.mutation_count\s*\}\}", members.strip()
    ), (
        f"the mutation entry in --expect declares {members!r} planned members. It must carry "
        "`*${{ needs.detect.outputs.mutation_count }}` — the shard count detect's plan packed "
        "the diff into, and the only thing that makes a missing shard visible to the gate"
    )


def test_the_mutation_shard_declares_the_namespace_it_owns(workflow: dict[str, Any]) -> None:
    # mutation.py writes one verdict per MODULE under `mutation/`, not under the
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


# A required check whose latest run is `skipped` counts as PASSING, so the gate
# may never skip: with select-runner failed every lane skips, and a gate that
# skipped with them would publish green. And no step may special-case a PR
# edit: ci.yml does not run on `edited` at all (a retarget re-runs it from
# pr-title.yml), so an edit guard here would be dead code.


def test_the_gate_never_skips_and_never_special_cases_an_edit(workflow: dict[str, Any]) -> None:
    gate = _gate(workflow)

    assert "always()" in str(gate.get("if", ""))
    for step in gate["steps"]:
        assert "edited" not in str(step.get("if", "")), step


# ---------------------------------------------------------------------------
# Grouped jobs. lint-node, lint-python, lint-mixed, scan, python-audit and
# ts-build-test each run a dozen checks as `continue-on-error` steps, so a red
# check only fails the job if the aggregating step names it — and only shows on
# the PR if the status step names it. A check missing from that one list is a
# check that can fail in silence.
# ---------------------------------------------------------------------------

AGGREGATE = "verdict.py step-outcomes"
POST = "verdict.py post-statuses"
# Setup inside a grouped job that may fail without being a check of its own:
# the check that needs it fails in its place.
SETUP_STEPS = {"alert-rule-tools", "jscpd-start"}


def _grouped_jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: job
        for name, job in workflow["jobs"].items()
        if any(AGGREGATE in str(s.get("run", "")) for s in job.get("steps", []))
    }


def _checks_env(job: dict[str, Any], command: str) -> dict[str, Any]:
    (step,) = [s for s in job["steps"] if command in str(s.get("run", ""))]
    return mapping(step["env"])


CHECK_PAIR = re.compile(r"([\w-]+)=\$\{\{\s*steps\.([\w-]+)\.outcome\s*\}\}")


def test_every_check_step_is_aggregated_and_posted(workflow: dict[str, Any]) -> None:
    grouped = _grouped_jobs(workflow)
    assert grouped, "no grouped job runs verdict.py step-outcomes"
    for name, job in grouped.items():
        pairs = CHECK_PAIR.findall(str(_checks_env(job, AGGREGATE)["CHECKS"]))
        for check, step_id in pairs:
            assert check == step_id, f"{name}: check {check} reports step {step_id}'s outcome"
        listed = {check for check, _ in pairs}
        steps = {
            s["id"]
            for s in job["steps"]
            if s.get("continue-on-error") and s.get("id") and s["id"] not in SETUP_STEPS
        }
        assert steps == listed, (
            f"{name}: continue-on-error checks {sorted(steps)} vs CHECKS {sorted(listed)} — a "
            "check missing from CHECKS fails without failing the job"
        )


SPAWN = re.compile(r"runner\.py spawn ([\w-]+) ")


def test_every_spawned_check_reports_through_a_join_step_named_after_it(
    workflow: dict[str, Any],
) -> None:
    # A spawned check reports nothing by itself: without its join step it runs,
    # fails, and no outcome, status or verdict ever sees it.
    spawned = 0
    for name, job in workflow["jobs"].items():
        steps = job.get("steps", [])
        for start in steps:
            found = SPAWN.search(str(start.get("run", "")))
            if not found:
                continue
            spawned += 1
            check = found.group(1)
            (joiner,) = [
                s
                for s in steps
                if str(s.get("run", "")) == f"python3 scripts/ci/runner.py join {check}"
            ]
            assert joiner["id"] == check, f"{name}: {check} joins as step {joiner['id']}"
            assert joiner["if"] == f"steps.{start['id']}.outcome == 'success'", (name, check)
            assert joiner.get("continue-on-error") is True, (name, check)
            assert steps.index(joiner) > steps.index(start), (name, check)
    assert spawned, "no job spawns a background check"


def test_every_posted_check_has_an_area(workflow: dict[str, Any]) -> None:
    # post-statuses refuses a check with no area, which would red the job on
    # the first run that reaches it.
    for name, job in _grouped_jobs(workflow).items():
        checks = {check for check, _ in CHECK_PAIR.findall(str(_checks_env(job, POST)["CHECKS"]))}
        assert checks - set(verdict.CHECK_AREAS) == set(), name


def test_the_statuses_and_the_verdict_read_one_list(workflow: dict[str, Any]) -> None:
    # Two copies of the list drift; the posting step and the verdict share one
    # YAML anchor, which PyYAML resolves to the very same mapping.
    for name, job in _grouped_jobs(workflow).items():
        assert _checks_env(job, POST) is _checks_env(job, AGGREGATE), (
            f"{name}: the statuses and the verdict read different check lists"
        )


def test_a_reused_check_is_one_the_lane_table_maps(workflow: dict[str, Any]) -> None:
    # A step skips on `reused_checks` containing its id, and reuse-plan only ever
    # names a lane-table `ci_check`. An id the table does not map is never
    # reused, which is safe; a table entry no step reads is dead.
    lanes = json.loads((REPO_ROOT / "scripts" / "dev" / "verify-lanes.json").read_text())
    mapped = {lane["ci_check"] for lane in lanes["lanes"] if lane.get("ci_check")}
    gated: set[str] = set()
    for job in _grouped_jobs(workflow).values():
        for step in job["steps"]:
            found = re.search(r"reused_checks \|\| '\[\]'\), '([^']+)'\)", str(step.get("if", "")))
            if found:
                gated.add(found.group(1))
    assert mapped <= gated, f"lane-table checks no step reuses on: {sorted(mapped - gated)}"


# ---------------------------------------------------------------------------
# Readable the moment a check fails. A job's verdict used to upload at its very
# end, and its log only once the whole RUN ended — 30 min after a lint check
# went red. Each check now runs under `verdict.py check`, which writes its own
# `<job>/<check>` verdict from what it printed, and an upload right after it
# ships that verdict while the job keeps going.
# ---------------------------------------------------------------------------

CHECK_SHELL = re.compile(
    r"^python3 (?:\.\./\.\./)?scripts/ci/verdict\.py check\b.* -- bash .*\{0\}$"
)


def _check_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in job["steps"]
        if s.get("continue-on-error") and s.get("id") and not str(s["id"]).endswith("-start")
    ]


def test_every_grouped_run_check_writes_its_own_verdict(workflow: dict[str, Any]) -> None:
    for name, job in _grouped_jobs(workflow).items():
        for step in _check_steps(job):
            if "run" not in step:
                continue
            assert CHECK_SHELL.match(str(step.get("shell", ""))), (
                f"{name}/{step['id']}: a check step's shell must be `verdict.py check -- bash … {{0}}`, "
                "or a red check reports only '<tool> failed'"
            )


def test_every_check_is_followed_by_an_upload_of_the_verdicts_so_far(
    workflow: dict[str, Any],
) -> None:
    for name, job in _grouped_jobs(workflow).items():
        steps = job["steps"]
        for step in _check_steps(job):
            after = steps[steps.index(step) + 1 :]
            upload = next((s for s in after if s.get("uses") == UPLOAD_VERDICT), None)
            assert upload is not None and _is_partial(upload), (
                f"{name}/{step['id']}: the next upload after this check must be a partial one, "
                "or its verdict waits for the end of the job"
            )
            between = after[: after.index(upload)]
            assert all(s.get("continue-on-error") is not True for s in between), (
                f"{name}/{step['id']}: another check runs before its verdict is uploaded"
            )


def test_a_partial_upload_runs_only_when_a_failing_verdict_is_waiting(
    workflow: dict[str, Any],
) -> None:
    pending = f"env.{verdict.PENDING_UPLOAD_ENV} == '1'"
    partials = 0
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if step.get("uses") == UPLOAD_VERDICT and _is_partial(step):
                partials += 1
                assert pending in str(step.get("if", "")), (name, step.get("if"))
                assert "always()" in str(step.get("if", "")), name
    assert partials, "no job uploads its verdicts mid-run"


def test_a_partial_upload_overwrites_the_jobs_own_artifact(workflow: dict[str, Any]) -> None:
    # Two names would put one lane in front of the gate twice; the composite
    # overwrites, so a partial upload must name the artifact the job ends with.
    for name in _reporting_jobs(workflow):
        job = workflow["jobs"][name]
        uploads = [s for s in job["steps"] if s.get("uses") == UPLOAD_VERDICT]
        finals = {str(s["with"]["name"]) for s in uploads if not _is_partial(s)}
        for step in uploads:
            if not _is_partial(step):
                continue
            given = str(step["with"]["name"]).replace("${{ github.job }}", name)
            assert given in finals, f"{name}: partial upload {given!r} is not one of {finals}"
