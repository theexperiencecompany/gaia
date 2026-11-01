#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["defusedxml==0.7.1"]
# ///
"""verdict.py — turning what a run produced into a verdict a reader can act on.

Every subcommand here takes raw output from something else — a diff, a JUnit
report, a linter's stdout, a job's step outcomes — and answers one question
about it, loudly, with the exact reason on failure.

`emit` is the ONLY producer of the verdict contract, and every gated lane goes
through it, because the three things a reader needs were three things a lane
could forget separately: the inline `::error file=,line=` annotation, the
step-summary block, and a machine-readable file an agent can read without
scrolling a 190k-line log. Written from one call they cannot drift apart.
`consolidate` is the other half: the gate reads every lane's file, and a lane
that reported NOTHING is a failure too — silence is how a lane stops running
without anybody noticing.

Subcommands:
    emit --lane L (--status S --summary "…" | --job-status <job.status>)
         [--finding f:l:msg [--detail-file p]]… [--advice "…"]…
         [--findings F] [--out DIR] [--only-if-missing]
        Write <out>/<lane>.json, annotate, summarise, and print the one-line
        human verdict. Always exits 0: it reports, it does not decide
        (`ci_verdict_die` in lib/log.sh is the dying call site). `--job-status`
        is what the upload-verdict composite passes for a lane that wrote no
        verdict of its own — see JOB_STATUS_VERDICT.
    dir
        Print the directory `emit` writes to, by the same resolution:
        $GAIA_VERDICT_DIR, else $RUNNER_TEMP/verdicts, else the checkout's
        verify-logs/verdicts. For scripts that need the path — read it, never
        re-derive it.
    check-ownership --family F [--out DIR]
        Exit 1 naming any verdict in the directory whose lane this job does not
        own, so a stray file is a red line pointing at itself rather than a
        phantom lane in the gate's table.
    consolidate DIR --expect "job[@family][*planned-members][=job-result],…"
        The gate's verdict. Print the table every lane's JSON forms and exit 1
        if any lane failed, timed out, errored — or never reported at all.
    pytest-verdict <junit.xml> --lane L [--path-prefix P] [--out DIR]
        Turn a pytest JUnit report into a verdict: one finding per failed test,
        at its own file and line, with the assertion tail as the detail.
    regression-proof-select <pr_file> <base_file> [<pr_file> <base_file> ...]
        Print one pytest node id per line for every `@pytest.mark.regression`
        test the PR ADDS. Driven by `pytest.sh regression-proof`.
    regression-proof-verdict <junit.xml> [--lane L] [--path-prefix P] [--out DIR]
        Decide whether the base-revision run actually proved anything: every
        regression test must have FAILED — not passed, not skipped, and not
        merely errored.
    collect --into <findings.jsonl> [--fallback <path>]
        Read mypy/tsc/ruff/biome/bandit output on stdin and append its
        file:line findings to a JSONL that `emit` and `step-outcomes` fold
        into the lane's one verdict. `--fallback` pins the whole output to one
        path for a tool that names a package rather than a line (syncpack,
        manypkg, nx). Prints nothing — annotating here too would put
        every finding on the page twice.
    check [--lane L] [--fallback F] [--path-prefix P] -- <command...>
        A check step's shell: run the command, stream its output, and when it
        fails write `<job>/<step id>`'s verdict from what it printed (every
        file:line it names, else its first error lines) and flag the job's next
        upload step. Exits with the command's code.
    sarif <report.sarif> --lane L [--out DIR]
        Write a failed scanner step's verdict (gitleaks, semgrep) from its SARIF
        report: one finding per result, at its location.
    step-outcomes --lane L [--reused JSON] [--out DIR] <name>=<outcome> [...]
        Fail a job when any of its `continue-on-error` steps failed, naming
        every one that did. A skipped step (nothing to check, or reused) passes.
    post-statuses --repo R --sha S --run-id N --run-attempt A [--reused JSON] <name>=<outcome> [...]
        Post one `ci / <area> / <name>` commit status per check, linked to the
        job that ran it, so a grouped job's checks each show on the PR, sorted
        into their area (CHECK_AREAS).

Interpreters: the JUnit readers need defusedxml and are invoked with
`uv run --no-project` (the PEP 723 block above is what supplies it); the rest
are stdlib-only and run under a plain `python3` / the suite's venv. That is why
defusedxml is imported inside the subcommands that need it rather than at
module level — a top-level import would break every plain-`python3` call.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import NamedTuple, TypedDict

from lib import nx_affected, output_findings
from lib.github import GitHub, GitHubError, Json, field_of, records, text_of
from lib.output_findings import Finding

REPO_ROOT = Path(__file__).resolve().parents[2]
# Where verdicts go, most specific first. The checkout is LAST on purpose: a
# self-hosted workspace persists between jobs (`clean:` is false there), so a
# previous job's verdicts sit in the tree waiting to be uploaded by the next
# one — stale lanes from another PR reaching a gate. And anything else running
# in the job that writes there pollutes the lane's verdict: run 34586506166's
# gate table carried `mutation/app/does_not_exist.py`, a fixture from an
# end-to-end TEST that `test-harness-tools` had just run, reported as a lane.
# RUNNER_TEMP is per-job and GitHub wipes it, so it is right by construction on
# a runner; `verify-logs/verdicts` stays the answer on a dev machine.
VERDICT_DIR_ENV = "GAIA_VERDICT_DIR"
CHECKOUT_VERDICT_DIR = REPO_ROOT / "verify-logs" / "verdicts"


def default_out_dir() -> Path:
    """Return the verdict directory when no `--out` says otherwise."""
    override = os.environ.get(VERDICT_DIR_ENV)
    if override:
        return Path(override)
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp) / "verdicts"
    return CHECKOUT_VERDICT_DIR


class Status(StrEnum):
    """The five things a lane can have done. `status` in the contract."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    TIMED_OUT = "timed_out"
    ERROR = "error"


# A lane that timed out did not pass — the gate goes red on it. It reads
# `timed_out` rather than `fail` because the two need opposite reactions: a
# failure has a finding to go read, a timeout has a cap to go raise or a diff
# to go split, and printing "failure" for the second sent agents hunting a
# finding that was never written.
FAILING_STATUSES = frozenset({Status.FAIL, Status.ERROR, Status.TIMED_OUT})

# Worst first — what consolidate reports for the run as a whole.
STATUS_PRECEDENCE = (Status.ERROR, Status.FAIL, Status.TIMED_OUT, Status.SKIP, Status.PASS)

ANNOTATION_LEVEL = {
    Status.PASS: "notice",
    Status.SKIP: "warning",
    Status.TIMED_OUT: "warning",
    Status.FAIL: "error",
    Status.ERROR: "error",
}


# One line of the gate's table: which lane, what it did, and the sentence a
# reader starts from.
Row = tuple[str, "Status", str]


class VerdictDoc(TypedDict):
    """The on-disk contract: verify-logs/verdicts/<lane>.json."""

    lane: str
    status: str
    summary: str
    findings: list[Finding]
    advice: list[str]


def _escape(text: str) -> str:
    """GitHub's workflow-command escaping — a raw newline ends the annotation."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def verdict_path(lane: str, out_dir: Path) -> Path:
    # A lane id may name a sub-unit (`test-python/unit-a`, `mutation/app-x`),
    # and that slash is a real directory: the shard jobs of one matrix then
    # write side by side instead of racing for one file name.
    return out_dir / f"{lane}.json"


def lane_already_reported(lane: str, out_dir: Path) -> bool:
    """Has anything in this tree already claimed ``lane``?

    By CONTENT, not by file name. Two producers may write one lane id under
    different names — the mutation gate writes lane `mutation/shard-2` as
    `mutation/_shard-2.json`, where `verdict_path` would look for
    `mutation/shard-2.json` — and checking the path alone would let this
    action's status-derived fallback sit beside the real, finding-carrying
    verdict under the same lane id.
    """
    if not out_dir.is_dir():
        return False
    return any(json.loads(p.read_text())["lane"] == lane for p in out_dir.rglob("*.json"))


# Set in the job's environment when a failing verdict is written, and cleared by
# the upload composite's `partial` mode: the upload step after every check runs
# only while this is set, so a red check's verdict reaches `mise ci:remote`
# minutes before its job ends instead of with it.
PENDING_UPLOAD_ENV = "GAIA_VERDICT_PENDING"


def flag_pending_upload() -> None:
    """Ask the job's next upload step to ship the verdicts written so far."""
    job_env = os.environ.get("GITHUB_ENV")
    if job_env:
        with Path(job_env).open("a") as handle:
            handle.write(f"{PENDING_UPLOAD_ENV}=1\n")


def write_verdict(doc: VerdictDoc, out_dir: Path) -> Path:
    path = verdict_path(doc["lane"], out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    if Status(doc["status"]) in FAILING_STATUSES:
        flag_pending_upload()
    return path


def location(finding: Finding) -> str:
    """Return `file:line`, or "" for a finding the tool gave no location."""
    if not finding["file"]:
        return ""
    return f"{finding['file']}:{finding['line']}" if finding["line"] else finding["file"]


def _summary_block(doc: VerdictDoc) -> str:
    status = doc["status"]
    lines = [f"### {doc['lane']} — {status}", "", doc["summary"], ""]
    for finding in doc["findings"]:
        where = location(finding)
        lines.append(f"- `{where}` {finding['message']}" if where else f"- {finding['message']}")
        detail = finding.get("detail")
        if detail:
            lines += [
                "",
                "<details><summary>detail</summary>",
                "",
                "```",
                detail,
                "```",
                "",
                "</details>",
                "",
            ]
    lines += [f"- advice: {a}" for a in doc["advice"]]
    return "\n".join(lines) + "\n"


def announce(doc: VerdictDoc, *, annotated: frozenset[str] = frozenset()) -> None:
    """Annotate every finding, append the step-summary block, print the verdict.

    All three, or none — forgetting one of them separately is the bug this
    whole module exists to make impossible. `annotated` holds the locations the
    tool already annotated itself; those are not annotated twice.
    """
    status = Status(doc["status"])
    level = ANNOTATION_LEVEL[status]
    for finding in doc["findings"]:
        if finding["file"] and location(finding) in annotated:
            continue
        where = (
            f"file={finding['file']},line={finding['line']}"
            if finding["file"]
            else f"title={doc['lane']}"
        )
        print(f"::{level} {where}::{_escape(finding['message'])}")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a") as handle:
            handle.write(_summary_block(doc))

    # The LAST line of a step is its one-line verdict (lib/log.sh). A failing
    # lane gets a top-level annotation of its own: the findings list can be
    # empty (a lane that died before it could name anything), and a red lane
    # with no annotation at all is exactly the log nobody can triage.
    line = f"{doc['lane']}: {status.upper()} — {doc['summary']}"
    if status in FAILING_STATUSES:
        print(f"::error::{_escape(line)}", file=sys.stderr)
    elif status is Status.SKIP:
        print(f"::warning::{_escape(line)}", file=sys.stderr)
    else:
        print(line, file=sys.stderr)


def report(
    lane: str,
    status: Status,
    summary: str,
    *,
    findings: list[Finding] | None = None,
    advice: list[str] | None = None,
    out_dir: Path | None = None,
) -> VerdictDoc:
    """Write and announce one lane's verdict. Every producer goes through here."""
    doc: VerdictDoc = {
        "lane": lane,
        "status": str(status),
        "summary": summary,
        "findings": findings or [],
        "advice": advice or [],
    }
    write_verdict(doc, out_dir or default_out_dir())
    announce(doc)
    return doc


def _verdict_parser(prog: str, *, default_lane: str) -> argparse.ArgumentParser:
    """Return the flags every verdict-producing subcommand shares."""
    parser = argparse.ArgumentParser(prog=f"verdict.py {prog}")
    parser.add_argument("--lane", default=default_lane)
    parser.add_argument("--out", type=Path, default=default_out_dir())
    parser.add_argument(
        "--path-prefix",
        default="",
        help="prepended to every finding's path so it is repo-relative",
    )
    return parser


# ---------------------------------------------------------------------------
# emit
#
# The only producer. A lane calls it once, with everything it knows.
# ---------------------------------------------------------------------------


def read_findings(path: Path | None) -> list[Finding]:
    """Read a `collect` JSONL, or nothing when the lane's tools wrote none."""
    if path is None or not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class EmitUsageError(ValueError):
    """A malformed `--finding` / `--detail-file`, reported as usage, not a crash."""


# What a lane's verdict is when the lane itself never wrote one and all we have
# is the CALLER's `job.status`. This mapping lives here rather than as three
# `if:`-guarded steps in the composite because a composite's `success()` /
# `failure()` / `cancelled()` evaluate that COMPOSITE's own prior steps, not the
# job — so the failure branch never fires and every lane reported `pass`. Run
# 34584038269 shard 5/6 died in `setup-python-test-env` and uploaded
# `{"lane": "mutation/shard-4", "status": "pass"}`. A false pass is the single
# outcome this contract exists to prevent, so the status is now an input the
# caller fills from `${{ job.status }}` and the branching is right here, where a
# test can reach it.
JOB_STATUS_VERDICT: dict[str, tuple[Status, str, list[str]]] = {
    "success": (Status.PASS, "passed", []),
    "failure": (
        Status.FAIL,
        "the lane failed and has not adopted the verdict contract — "
        "its reason is only in this job's log",
        ["Open this job's log. Then give the lane a `ci_verdict_die` so the next reader need not."],
    ),
    "cancelled": (
        Status.TIMED_OUT,
        "cancelled before it reported — it hit its timeout-minutes cap, or the run was superseded",
        [
            "Split the diff or raise this job's timeout-minutes. There is no finding to read: "
            "the lane never reached the end."
        ],
    ),
    "skipped": (Status.SKIP, "skipped", []),
}


def _take_findings(args: list[str]) -> tuple[list[Finding], list[str]]:
    """Pull the ordered `--finding` / `--detail-file` pairs out of the arg list.

    Hand-parsed rather than given to argparse because `--detail-file` binds to
    the `--finding` it FOLLOWS: argparse has no notion of one option modifying
    the previous one, and the custom-Action version of this needed a parameter
    it never used.
    """
    findings: list[Finding] = []
    rest: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        index += 1
        if token not in ("--finding", "--detail-file"):
            rest.append(token)
            continue
        if index >= len(args):
            raise EmitUsageError(f"{token} needs a value")
        value = args[index]
        index += 1
        if token == "--detail-file":
            if not findings:
                raise EmitUsageError("--detail-file must follow the --finding it belongs to")
            findings[-1]["detail"] = Path(value).read_text()
            continue
        parts = value.split(":", 2)
        if len(parts) != 3 or not parts[1].strip().isdigit():
            raise EmitUsageError(f"--finding must be <file>:<line>:<message>, got {value!r}")
        findings.append({"file": parts[0], "line": int(parts[1]), "message": parts[2]})
    return findings, rest


def cmd_emit(args: list[str]) -> int:
    """Write one lane's verdict and exit 0 even on failure; `ci_verdict_die` is what dies."""
    parser = _verdict_parser("emit", default_lane="")
    parser.add_argument("--status", choices=[str(s) for s in Status])
    parser.add_argument("--summary")
    parser.add_argument(
        "--job-status",
        choices=sorted(JOB_STATUS_VERDICT),
        help=(
            "the CALLER's ${{ job.status }}. Derives status, summary and advice for a "
            "lane that wrote no verdict of its own. A composite cannot read this itself: "
            "its success()/failure()/cancelled() see only its OWN prior steps."
        ),
    )
    parser.add_argument("--advice", action="append", default=[])
    # The same JSONL `step-outcomes` reads. A lane with ONE tool has no step
    # outcomes to fold, but its tool's findings are no less worth carrying —
    # without this, adopting the contract meant losing the file:line.
    parser.add_argument(
        "--findings",
        type=Path,
        help="JSONL written by `verdict.py collect` — appended to any --finding given",
    )
    # A lane that died at its cap wrote nothing; the trailing step that notices
    # must not overwrite a real verdict when the lane DID report.
    parser.add_argument("--only-if-missing", action="store_true")
    try:
        findings, rest = _take_findings(args)
    except EmitUsageError as exc:
        parser.error(str(exc))
    opts = parser.parse_args(rest)
    if not opts.lane:
        parser.error("--lane is required")
    if bool(opts.status) == bool(opts.job_status):
        parser.error("give exactly one of --status (with --summary) or --job-status")

    derived_status, derived_summary, derived_advice = JOB_STATUS_VERDICT.get(
        opts.job_status or "", (Status.ERROR, "", [])
    )
    status = Status(opts.status) if opts.status else derived_status
    summary = opts.summary or derived_summary
    if not summary:
        parser.error("--status needs a --summary")

    if opts.only_if_missing and lane_already_reported(opts.lane, opts.out):
        return 0
    report(
        opts.lane,
        status,
        summary,
        findings=findings + read_findings(opts.findings),
        advice=opts.advice or derived_advice,
        out_dir=opts.out,
    )
    return 0


# ---------------------------------------------------------------------------
# consolidate
#
# The gate's verdict, and the enforcement: `--expect` is the list of lanes that
# MUST have reported. A lane with no file is `NO VERDICT` and fails the gate —
# that is what makes a lane unable to stop running quietly.
#
# Each `--expect` entry may carry the lane's GitHub job result (`lane=result`),
# which is the only way to tell the two silences apart: a `skipped` lane
# legitimately writes nothing (its language was untouched), while a `success`
# lane that wrote nothing has lost its reporting. The result is cross-checked
# against the verdicts rather than dropped once any of them turn up — see
# RESULT_OVERRIDE — and `lane@family*<n>` additionally demands one verdict per
# PLANNED matrix member, so a shard that died before its upload cannot be
# spoken for by the shard beside it.
# ---------------------------------------------------------------------------

# Verdict a lane's job result implies when the lane itself wrote no file.
RESULT_FALLBACK: dict[str, tuple[Status, str]] = {
    "skipped": (Status.SKIP, "skipped — change detection proved this lane had nothing to check"),
    "cancelled": (Status.TIMED_OUT, "cancelled — the lane hit its cap or the run was superseded"),
    "failure": (Status.ERROR, "NO VERDICT — the lane failed before it could report one"),
    "success": (Status.ERROR, "NO VERDICT — the lane passed but reported nothing"),
}
_NO_VERDICT = (Status.ERROR, "NO VERDICT — this lane never reported")

# `<job>@result-only`: a lane that CANNOT report. The upload composite is a path
# in the checked-out tree, so a job with no checkout at all (`probe`) or one
# pinned to another revision (`select-runner` checks out the DEFAULT BRANCH on
# purpose — it handles a PAT and must not run PR-authored code, so a composite
# this branch adds does not exist in its tree) can never run it. Such a lane is
# DECLARED here rather than quietly dropped from the list: the gate still fails
# on its job result, it just has no artifact to wait for. Silence from an
# undeclared lane stays a failure, which is the whole point of the list.
RESULT_ONLY_FAMILY = "result-only"
RESULT_ONLY: dict[str, tuple[Status, str]] = {
    "success": (Status.PASS, "passed (result-only — this job cannot run a local composite)"),
    "skipped": (Status.SKIP, "skipped"),
    "failure": (Status.FAIL, "the job failed — its reason is in its own log, not in a verdict"),
    "cancelled": (Status.TIMED_OUT, "cancelled — it hit its cap, or the run was superseded"),
}
_RESULT_ONLY_UNKNOWN = (Status.ERROR, "result-only, but the job result did not reach the gate")

# What a lane's JOB RESULT says when its verdicts do not say it themselves. A
# lane writes its verdict and then keeps running — releasing the test services,
# stopping the sidecar, uploading — and `emit --only-if-missing` stands down on
# a lane that already reported, so a step that reds the job AFTER the verdict is
# written leaves no trace in the tree at all. The result is then the only
# witness, and a gate that read the verdicts alone went green over a job GitHub
# calls failed. Only consulted when no verdict is already failing: a red lane
# that named its own finding must not be reported twice.
RESULT_OVERRIDE: dict[str, tuple[Status, str]] = {
    "failure": (
        Status.FAIL,
        "the job failed but every verdict it uploaded passed — a step outside the lane "
        "(setup, teardown, the upload) went red after the lane reported",
    ),
    "cancelled": (
        Status.TIMED_OUT,
        "cancelled after reporting — whatever it had not finished is missing from these verdicts",
    ),
}


def _is_member(lane: str, family: str) -> bool:
    """Is ``lane`` one MEMBER of ``family`` rather than a sub-unit of a member?

    A matrix member reports under `<family>/<member>` — `mutation/shard-3`,
    `test-python/unit-a` — and anything deeper belongs to one of them: the
    mutation shards write one verdict per mutated MODULE
    (`mutation/app/services/x.py`), many per shard. Counting every verdict in
    the family would let one shard's modules stand in for a shard that never ran.
    """
    return lane == family or "/" not in lane[len(family) + 1 :]


def _load_verdicts(directory: Path) -> dict[str, VerdictDoc]:
    found: dict[str, VerdictDoc] = {}
    for path in sorted(directory.rglob("*.json")):
        doc: VerdictDoc = json.loads(path.read_text())
        found[doc["lane"]] = doc
    return found


def _belongs(lane: str, family: str) -> bool:
    return lane == family or lane.startswith(f"{family}/")


def _matching_lanes(family: str, found: dict[str, VerdictDoc]) -> list[str]:
    """Every verdict belonging to one expected lane.

    A lane may report as a FAMILY of sub-units: `test-python` as one verdict per
    slice, `test-mutation` as one per mutated module across every shard. How
    many there are is decided at runtime (by the matrix, by `mutation.py plan`),
    so the gate expects the family and is satisfied by at least one member —
    a per-shard `--expect` list in YAML would drift from the planner on the
    first large diff.
    """
    return sorted(k for k in found if _belongs(k, family))


def _missing_members(lane: str, family: str, matched: list[str], planned: str) -> list[Row]:
    """Return the row a family owes when fewer members reported than were planned.

    `<job>@<family>*<n>` is how the runtime size of a matrix reaches the gate —
    `mutation.py plan` already emits the shard count it packed the diff into.
    Without it a family is satisfied by ANY member, so a shard killed before its
    `if: always()` upload (a job-level cap, a superseded run) is spoken for by
    its siblings and the modules it carried go unmutated, silently.
    """
    if not planned:
        return []
    reported = sum(1 for key in matched if _is_member(key, family))
    if reported >= int(planned):
        return []
    return [
        (
            lane,
            Status.ERROR,
            f"NO VERDICT — {reported} of {planned} planned matrix member(s) reported; "
            "the rest were cancelled or never uploaded, so their work is unproven",
        )
    ]


def _row_for(entry: str, found: dict[str, VerdictDoc]) -> list[Row]:
    """Return the table rows one `--expect` entry produces, and nothing else.

    Its own function because "what does this entry resolve to" is a separate
    question from "what does the gate do about it" — and because the four cases
    (result-only, family with members, family without, plain lane) had grown
    into a branch count the PLR ratchet was right to flag.
    """
    job, _, result = entry.partition("=")
    job, _, planned = job.partition("*")
    lane, _, family = job.partition("@")
    if family == RESULT_ONLY_FAMILY:
        return [(lane, *RESULT_ONLY.get(result, _RESULT_ONLY_UNKNOWN))]
    matched = _matching_lanes(family or lane, found)
    if not matched:
        return [(lane, *RESULT_FALLBACK.get(result, _NO_VERDICT))]
    rows = [(key, Status(found[key]["status"]), found[key]["summary"]) for key in matched]
    rows += _missing_members(lane, family or lane, matched, planned)
    if result in RESULT_OVERRIDE and not any(status in FAILING_STATUSES for _, status, _ in rows):
        rows.append((lane, *RESULT_OVERRIDE[result]))
    return rows


def consolidated_rows(expect: str, found: dict[str, VerdictDoc]) -> list[Row]:
    """One row per expected lane, then every verdict nobody expected."""
    rows = [_row_for(e.strip(), found) for e in expect.split(",") if e.strip()]
    claimed = {lane for group in rows for lane, _, _ in group}
    flat = [row for group in rows for row in group]

    # A verdict nobody expected still gets read. Dropping it would let a lane go
    # quiet by renaming itself, which is the failure this gate is for — and a
    # red one still has to red the gate.
    flat += [
        (key, Status(found[key]["status"]), found[key]["summary"])
        for key in sorted(set(found) - claimed)
    ]
    return flat


# ---------------------------------------------------------------------------
# dir
#
# The resolution, as a value other scripts can read. Re-deriving it in bash is
# how it goes wrong: `${GAIA_VERDICT_DIR:-$REPO_ROOT/verify-logs/verdicts}`
# looks equivalent but has no RUNNER_TEMP rung, so on a runner it names the
# checkout while the composite uploads from the runner's temp dir — every
# verdict written through it would miss the gate. One resolution, one owner.
# ---------------------------------------------------------------------------


def cmd_dir(args: list[str]) -> int:
    """Print the directory `emit` writes to. One line, nothing else."""
    argparse.ArgumentParser(prog="verdict.py dir").parse_args(args)
    print(default_out_dir())
    return 0


# ---------------------------------------------------------------------------
# check-ownership
#
# A job uploads a DIRECTORY, so it ships whatever is in it. Anything else in the
# job that writes a verdict — most obviously a test of the verdict machinery
# itself — rides along and reaches the gate as a lane nobody can find. Run
# 34586506166 consolidated `mutation/app/does_not_exist.py`, which is a fixture
# path from `test-harness-tools`'s own end-to-end test.
#
# "Belongs" is the same prefix rule `--expect` families use: a verdict belongs
# to this job if its lane IS the job's family or sits under `<family>/`. The
# family is the composite's `family` input, defaulting to its `lane` — the
# mutation shards pass `mutation`, because mutation.py writes one verdict per
# module under that namespace rather than under the shard's own lane.
# ---------------------------------------------------------------------------


def cmd_check_ownership(args: list[str]) -> int:
    """Exit 1 naming any verdict in the directory that this job does not own."""
    parser = argparse.ArgumentParser(prog="verdict.py check-ownership")
    parser.add_argument("--family", required=True)
    parser.add_argument("--out", type=Path, default=default_out_dir())
    opts = parser.parse_args(args)

    if not opts.out.is_dir():
        return 0
    lanes = [
        (path, json.loads(path.read_text())["lane"]) for path in sorted(opts.out.rglob("*.json"))
    ]
    strays = [(path, lane) for path, lane in lanes if not _belongs(lane, opts.family)]
    if not strays:
        return 0
    for path, lane in strays:
        print(f"::error file={path}::verdict for lane '{lane}', which this job does not own")
    print(
        f"::error::{len(strays)} foreign verdict(s) in {opts.out} — this job owns "
        f"'{opts.family}' and lanes under it. Something else in this job wrote there; "
        "uploading them would put lanes nobody can find in front of the gate.",
        file=sys.stderr,
    )
    return 1


GATE_LANE = "quality-gate"


def _write_gate_verdict(rows: list[Row], out_dir: Path) -> None:
    """Write the gate's verdict without announcing it — consolidate prints its own table.

    A reader of a red gate wants which lanes, not the gate's log: each lane that
    did not pass is one finding, named so its own verdict can be opened next.
    """
    bad = [(lane, status, summary) for lane, status, summary in rows if status in FAILING_STATUSES]
    findings: list[Finding] = [
        {"file": "", "line": 0, "message": f"{lane}: {str(status).upper()} — {summary}"}
        for lane, status, summary in bad
    ]
    write_verdict(
        {
            "lane": GATE_LANE,
            "status": str(Status.FAIL if bad else Status.PASS),
            "summary": f"{len(bad)} of {len(rows)} lane(s) did not pass"
            if bad
            else f"{len(rows)} lane(s) reported, none failing",
            "findings": findings,
            "advice": ["Each lane's own verdict carries its findings at file:line."] if bad else [],
        },
        out_dir,
    )


def cmd_consolidate(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verdict.py consolidate")
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--expect",
        required=True,
        help=(
            "comma-separated `<job>[@<family>][*<planned members>][=<github job result>]` "
            "entries. "
            "<job> is the gate's needs entry, and by default also the lane id to "
            "look for; @<family> names a different one when the job and its lane "
            "ids differ (test-mutation@mutation — the mutation gate reports one "
            "verdict per MODULE, not one per job). A family is satisfied by any "
            "verdict whose lane is it or starts with `<family>/`, because how "
            "many members there are is decided at runtime; `*<n>` pins that "
            "number where the planner knows it, so a matrix member cancelled "
            "before it could upload cannot be spoken for by its siblings. A "
            "failure/cancelled job result reds the lane even when every verdict "
            "it did upload passed — a step that goes red AFTER the lane reported "
            "leaves no other trace. "
            "The family `result-only` (select-runner@result-only) marks a job that "
            "CANNOT report — no checkout, or a checkout pinned to another revision, "
            "so it can never run the local upload composite. It is still enforced on "
            "its job result; it just has no verdict to wait for. Declaring it is the "
            "point: an undeclared lane that reports nothing still fails the gate."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="also write the gate's own verdict here: one finding per lane that did not pass",
    )
    opts = parser.parse_args(args)

    found = _load_verdicts(opts.directory) if opts.directory.is_dir() else {}
    # A re-run gate downloads the verdict an earlier attempt of itself uploaded;
    # it is this gate's output, never one of its lanes.
    found.pop(GATE_LANE, None)
    rows = consolidated_rows(opts.expect, found)
    if opts.out:
        _write_gate_verdict(rows, opts.out)

    print("::group::Per-lane verdicts")
    for lane, status, summary in rows:
        print(f"  {lane + ':':<28} {status!s:<10} {summary}")
    print("::endgroup::")

    bad = [(lane, status, summary) for lane, status, summary in rows if status in FAILING_STATUSES]
    for lane, status, summary in bad:
        print(f"::error::{lane}: {str(status).upper()} — {_escape(summary)}")
        doc = found.get(lane)
        for finding in doc["findings"] if doc else []:
            print(f"    {location(finding) or '-'}  {finding['message']}")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        table = ["| lane | status | summary |", "| --- | --- | --- |"]
        table += [f"| `{lane}` | {status} | {summary} |" for lane, status, summary in rows]
        with Path(summary_file).open("a") as handle:
            handle.write("\n".join(table) + "\n")

    worst = next((s for s in STATUS_PRECEDENCE if any(r[1] is s for r in rows)), Status.PASS)
    if bad:
        print(
            f"quality-gate: {str(worst).upper()} — {len(bad)} of {len(rows)} lane(s) did not pass"
        )
        return 1
    print(f"quality-gate: PASSED — {len(rows)} lane(s) reported")
    return 0


# ---------------------------------------------------------------------------
# regression-proof-select
#
# Reads pairs of (test file in the PR, same file at the base revision — or a
# missing path when the file is new) and prints one pytest node id per line for
# every `@pytest.mark.regression` test function present in the PR copy but
# absent from the base copy. Only those must go red on base: a marked test whose
# fix already merged is green on base by design and proves nothing about this PR.
# ---------------------------------------------------------------------------

REGRESSION_MARK = "regression"


def _is_regression_mark(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == REGRESSION_MARK


def _mentions_regression_mark(node: ast.AST) -> bool:
    return any(_is_regression_mark(sub) for sub in ast.walk(node) if isinstance(sub, ast.expr))


def _pytestmark_is_regression(body: list[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            if _mentions_regression_mark(stmt.value):
                return True
    return False


def _test_ids(source: str, *, marked_only: bool) -> set[str]:
    """Return test node ids in ``source``; with ``marked_only``, only regression-marked ones.

    The mark counts on the function, its class, the module's ``pytestmark``, or
    a ``pytest.param`` case.
    """
    tree = ast.parse(source)
    module_marked = _pytestmark_is_regression(tree.body)
    ids: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.Module):
            continue
        prefix = f"{node.name}::" if isinstance(node, ast.ClassDef) else ""
        scope_marked = module_marked or (
            isinstance(node, ast.ClassDef)
            and (
                any(_is_regression_mark(d) for d in node.decorator_list)
                or _pytestmark_is_regression(node.body)
            )
        )
        for child in node.body:
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not child.name.startswith("test_"):
                continue
            if marked_only and not (
                scope_marked or any(_mentions_regression_mark(d) for d in child.decorator_list)
            ):
                continue
            ids.add(f"{prefix}{child.name}")
    return ids


def _mark_present_in_text(source: str) -> bool:
    return f"mark.{REGRESSION_MARK}" in source


def cmd_regression_proof_select(args: list[str]) -> int:
    if not args or len(args) % 2:
        print(
            "usage: verdict.py regression-proof-select <pr_file> <base_file> ...",
            file=sys.stderr,
        )
        return 2
    for pr_file, base_file in zip(args[::2], args[1::2], strict=True):
        pr_path, base_path = Path(pr_file), Path(base_file)
        pr_source = pr_path.read_text()
        marked = _test_ids(pr_source, marked_only=True)
        if _mark_present_in_text(pr_source) and not marked:
            print(
                f"ERROR: regression-proof — {pr_file} mentions pytest.mark.{REGRESSION_MARK} but no "
                "test could be attributed to it (unsupported placement). Put the mark on the test "
                "function, its class, the module's pytestmark, or a pytest.param case.",
                file=sys.stderr,
            )
            return 1
        existing = (
            _test_ids(base_path.read_text(), marked_only=False) if base_path.exists() else set()
        )
        for test_id in sorted(marked - existing):
            print(f"{pr_file}::{test_id}")
    return 0


# ---------------------------------------------------------------------------
# regression-proof-verdict
#
# Reads the JUnit XML of the base-revision run (see `pytest.sh regression-proof`)
# and applies one rule per `@pytest.mark.regression` test:
#
#     it must FAIL — an assertion that goes red without the fix.
#
# PASSED is the obvious rejection: a test green on base does not pin the bug it
# claims to. ERROR-only is rejected too, and that is the subtler half. An error
# is a test that never reached its assertions — a missing fixture, an import of
# a symbol the base does not have, a service that would not start. It looks like
# proof in a summary line ("did not pass") while proving nothing about the bug,
# which is exactly how this gate spent its life reporting success it had not
# earned. A test that both fails and then errors in teardown is fine: the
# assertion still ran.
# ---------------------------------------------------------------------------


# The last `<path>.py:<line>:` line of a pytest traceback is where the assertion
# actually blew up. That is the only place a real report records it: pytest's
# default xunit2 family writes NO file/line attributes on <testcase> (only the
# deprecated xunit1 does), so a reader of the attributes alone annotates every
# failure at line 1 of nothing — which is what the first cut of this did, and
# what a hand-written fixture could never have caught.
_TRACEBACK_LOCATION = re.compile(r"^(?P<file>\S+\.py):(?P<line>\d+): ", re.MULTILINE)


def _location_from_traceback(text: str) -> tuple[str, int] | None:
    matches = _TRACEBACK_LOCATION.findall(text)
    if not matches:
        return None
    file_path, line = matches[-1]
    return file_path, int(line)


JUNIT_ERROR_LINES = 20
JUNIT_TAIL_LINES = 25


def _junit_detail(text: str) -> str:
    """Put the `E ` lines first — the assertion a reader opens it for — then the traceback's tail."""
    lines = text.splitlines()
    errors = [line[1:].strip() for line in lines if line.startswith("E ")][:JUNIT_ERROR_LINES]
    tail = lines[-JUNIT_TAIL_LINES:]
    return "\n".join([*errors, "--", *tail] if errors else tail)


class JUnitCase(NamedTuple):
    """One `<testcase>`, flattened to what a verdict needs from it."""

    name: str
    file: str
    line: int
    failed: bool
    errored: bool
    skipped: bool
    detail: str


def _read_junit(path: str, path_prefix: str = "") -> list[JUnitCase]:
    """Parse a pytest JUnit report into cases with their source location.

    ``path_prefix`` makes the paths repo-relative: pytest records them relative
    to its own rootdir (``tests/...`` when run from apps/api), and an annotation
    on a path GitHub cannot resolve renders nowhere.
    """
    # Imported here, not at module level: only the JUnit readers need a
    # third-party parser, and only they are invoked through `uv run
    # --no-project` (which resolves the PEP 723 block above). Every other
    # subcommand runs under a plain python3 that has no defusedxml.
    from defusedxml.ElementTree import parse as parse_xml

    root = parse_xml(path).getroot()
    cases: list[JUnitCase] = []
    for case in root.iter("testcase"):
        problems = [n for tag in ("failure", "error") for n in case.iter(tag)]
        text = "\n".join(p.text or p.get("message", "") for p in problems)
        location = _location_from_traceback(text)
        if location is None:
            # xunit1 is the only family that puts file/line on the testcase, and
            # it is the deprecated one; when the traceback gave us nothing, fall
            # back to these. `line` is 0-based there, annotations are 1-based.
            location = (case.get("file", ""), int(case.get("line", "0")) + 1)
        cases.append(
            JUnitCase(
                name=f"{case.get('classname', '')}::{case.get('name', '')}".lstrip(":"),
                file=f"{path_prefix}{location[0]}",
                line=location[1],
                failed=case.find("failure") is not None,
                errored=case.find("error") is not None,
                skipped=case.find("skipped") is not None,
                detail=_junit_detail(text),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# pytest-verdict
#
# The test lanes had no structured output at all: the verdict of a slice was
# the last hundred lines of a 20k-line log, with no annotation anywhere — so a
# red slice showed nothing on the PR's Files tab. The JUnit report they already
# write carries the traceback each failure's location can be read out of.
# ---------------------------------------------------------------------------


def cmd_pytest_verdict(args: list[str]) -> int:
    """Emit a slice's verdict from the JUnit report it already wrote."""
    parser = _verdict_parser("pytest-verdict", default_lane="")
    parser.add_argument("junit")
    # The slice's own exit code: pytest can fail for reasons JUnit does not
    # record (a collection abort, the flake gate), and a verdict that says
    # `pass` over a red step is worse than none.
    parser.add_argument("--exit-code", type=int, default=0)
    opts = parser.parse_args(args)
    if not opts.lane:
        parser.error("--lane is required")

    try:
        cases = _read_junit(opts.junit, opts.path_prefix)
    except OSError:
        report(
            opts.lane,
            Status.ERROR if opts.exit_code else Status.SKIP,
            f"no JUnit report at {opts.junit} — pytest collected nothing or never ran",
            out_dir=opts.out,
        )
        return 0

    broken = [c for c in cases if c.failed or c.errored]
    findings: list[Finding] = [
        {
            "file": c.file,
            "line": c.line,
            "message": f"{'ERROR' if c.errored and not c.failed else 'FAILED'} {c.name}",
            "detail": c.detail,
        }
        for c in broken
    ]
    if broken:
        report(
            opts.lane,
            Status.FAIL,
            f"{len(broken)} of {len(cases)} test(s) did not pass",
            findings=findings,
            advice=[
                "Reproduce one test at a time: `uv run pytest <nodeid> -p no:xdist -o addopts=''`."
            ],
            out_dir=opts.out,
        )
        return 0
    if opts.exit_code:
        report(
            opts.lane,
            Status.FAIL,
            f"every test passed but the step exited {opts.exit_code} "
            "— a flake-gate rerun, a coverage miss or a collection abort",
            advice=["The reason is in the step's own output; JUnit records no failure for it."],
            out_dir=opts.out,
        )
        return 0
    report(opts.lane, Status.PASS, f"{len(cases)} test(s) passed", out_dir=opts.out)
    return 0


def cmd_regression_proof_verdict(args: list[str]) -> int:
    """Exit 0 when every regression test failed on base, 1 otherwise."""
    parser = _verdict_parser("regression-proof-verdict", default_lane="regression-proof")
    parser.add_argument("junit")
    opts = parser.parse_args(args)

    try:
        cases = _read_junit(opts.junit, opts.path_prefix)
    except OSError as exc:
        report(
            opts.lane,
            Status.ERROR,
            f"cannot read the JUnit report: {exc}",
            advice=[
                "The base run wrote no report — check the step above for why pytest never ran."
            ],
            out_dir=opts.out,
        )
        return 1

    # One test can emit several <testcase> entries (call + teardown), so fold
    # them together and ask what happened across all of them.
    failed: dict[str, bool] = defaultdict(bool)
    errored: dict[str, bool] = defaultdict(bool)
    skipped: dict[str, bool] = defaultdict(bool)
    where: dict[str, tuple[str, int]] = {}
    for case in cases:
        failed[case.name] |= case.failed
        errored[case.name] |= case.errored
        skipped[case.name] |= case.skipped
        where.setdefault(case.name, (case.file, case.line))

    if not failed:
        report(
            opts.lane,
            Status.ERROR,
            "the JUnit report lists no tests at all — the run did not execute",
            advice=["A run that executed nothing is a failure, not a pass. Check the step above."],
            out_dir=opts.out,
        )
        return 1

    # A skip is neither a failure nor an error in JUnit, so folding it into
    # "passed" is how a test that never ran got reported as "PASS on base" —
    # with the advice to delete the fix. The contract tier is guarded by
    # `USE_REAL_SERVICES`, so any regression test in it skips wherever the lane
    # forgets to export it, which is every local run of this script.
    skipped_only = sorted(n for n in failed if skipped[n] and not failed[n] and not errored[n])
    passed_on_base = sorted(
        n for n in failed if not failed[n] and not errored[n] and not skipped[n]
    )
    errored_only = sorted(n for n in failed if errored[n] and not failed[n])
    proven = sorted(n for n in failed if failed[n])

    # A table rather than three near-identical if-blocks: they differed only in
    # their label and their advice, and each new outcome added another branch to
    # a function the complexity ratchet already watches. Ordered by what a reader
    # most needs to hear first.
    for label, names, advice in (
        (
            "PASS",
            passed_on_base,
            (
                "A regression test must go red without its fix. Either the fix is",
                "not needed, or the test does not exercise the bug it names.",
            ),
        ),
        (
            "SKIPPED",
            skipped_only,
            (
                "A skip is not proof — the test never ran, so it says nothing about",
                "whether the bug exists on base. Give the run whatever the test skips",
                "for (the contract tier needs USE_REAL_SERVICES=1 plus live Mongo and",
                "Redis), or move the proof to a tier that runs here.",
            ),
        ),
        (
            "ERRORED",
            errored_only,
            (
                "An error is not proof: the test never reached its assertions, so it",
                "shows the harness broke, not that the bug is caught. Make it runnable",
                "against the base revision — assert on behavior rather than importing",
                "symbols the fix introduces.",
            ),
        ),
    ):
        if not names:
            continue
        print(f"ERROR: regression-proof — {len(names)} test(s) {label} on base:")
        for name in names:
            print(f"  {name}")
        findings: list[Finding] = [
            {
                "file": where[name][0],
                "line": where[name][1],
                "message": f"{label} on base — a regression test must go red without its fix",
            }
            for name in names
        ]
        report(
            opts.lane,
            Status.FAIL,
            f"{len(names)} regression test(s) {label} on base instead of failing",
            findings=findings,
            advice=[" ".join(advice)],
            out_dir=opts.out,
        )
        return 1

    print(f"regression-proof: {len(proven)} regression test(s) fail on base as required")
    for name in proven:
        print(f"  FAILED {name}")
    report(
        opts.lane,
        Status.PASS,
        f"{len(proven)} regression test(s) fail on base as required",
        out_dir=opts.out,
    )
    return 0


# ---------------------------------------------------------------------------
# collect / check
#
# A tool's output, read back as findings (lib/output_findings.py). `collect`
# feeds a lane that emits its own verdict; `check` is the shell every gated
# check step runs under, so a red check writes its own verdict the moment it
# fails, whatever the tool printed.
# ---------------------------------------------------------------------------


def cmd_collect(args: list[str]) -> int:
    """Append stdin's file:line findings to a JSONL the lane's verdict will carry.

    It deliberately prints NOTHING. Annotating here and emitting the verdict
    later would put every finding on the page twice; the lane's single `emit`
    is the one producer, and this is how a tool's own output reaches it.
    """
    parser = argparse.ArgumentParser(prog="verdict.py collect")
    parser.add_argument("--into", type=Path, required=True)
    parser.add_argument(
        "--fallback",
        help="repo-relative path to pin a location-less result to (a manifest for syncpack)",
    )
    opts = parser.parse_args(args)

    text = sys.stdin.read()
    found = output_findings.read(text, fallback=opts.fallback)
    if not opts.fallback and found and not found[0]["file"]:
        found = []
    opts.into.parent.mkdir(parents=True, exist_ok=True)
    with opts.into.open("a") as handle:
        handle.writelines(json.dumps(f) + "\n" for f in found)
    return 0


def _default_check_lane() -> str:
    """`<job>/<step id>` — what a check step's verdict is called when nothing says otherwise."""
    job, step = os.environ.get("GITHUB_JOB", ""), os.environ.get("GITHUB_ACTION", "")
    return f"{job}/{step}" if job and step else ""


def _run_teeing(command: list[str]) -> tuple[int, str]:
    """Run ``command``, streaming its merged output to ours, and return (exit code, output)."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
        assert child.stdout is not None
        captured: list[bytes] = []
        for chunk in iter(child.stdout.readline, b""):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            captured.append(chunk)
        return child.wait(), b"".join(captured).decode("utf-8", "replace")


def cmd_check(args: list[str]) -> int:
    """Run one check; when it fails, write its verdict from what it printed and exit with its code.

    A workflow step uses this as its shell (`shell: python3 scripts/ci/verdict.py
    check -- bash -e {0}`), so the step body is unchanged. A check that wrote its
    own verdict keeps it; a passing check writes nothing (the job's rollup says so).
    """
    parser = _verdict_parser("check", default_lane=_default_check_lane())
    parser.add_argument("--fallback", help="file to pin a location-less result to")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    opts = parser.parse_args(args)
    command = opts.command[1:] if opts.command[:1] == ["--"] else opts.command
    if not command:
        parser.error("give the check's command after --")
    if not opts.lane:
        parser.error("--lane is required outside a workflow step (no GITHUB_JOB/GITHUB_ACTION)")

    rc, output = _run_teeing(command)
    if rc == 0:
        return 0
    flag_pending_upload()
    if lane_already_reported(opts.lane, opts.out):
        return rc
    findings = output_findings.read(output, fallback=opts.fallback, path_prefix=opts.path_prefix)
    located = sum(1 for f in findings if f["file"])
    check = opts.lane.rsplit("/", 1)[-1]
    summary = (
        f"{check}: {len(findings)} finding(s) (exit {rc})"
        if located
        else f"{check} failed (exit {rc}); its output names no file:line — its first error lines are attached"
    )
    # Written and announced here rather than through `report`: the tool already
    # annotated the locations it printed as `::error`, and those are not repeated.
    doc: VerdictDoc = {
        "lane": opts.lane,
        "status": str(Status.FAIL),
        "summary": summary,
        "findings": findings,
        "advice": [],
    }
    write_verdict(doc, opts.out)
    announce(doc, annotated=frozenset(output_findings.annotated_locations(output)))
    return rc


def _obj(value: object) -> Json:
    return value if isinstance(value, dict) else {}


def _objs(value: object) -> list[Json]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _sarif_findings(doc: Json) -> list[Finding]:
    """One finding per SARIF result, at its first physical location."""
    findings: list[Finding] = []
    for run in _objs(doc.get("runs")):
        for result in _objs(run.get("results")):
            locations = _objs(result.get("locations"))
            physical = _obj(locations[0].get("physicalLocation")) if locations else {}
            uri = str(_obj(physical.get("artifactLocation")).get("uri") or "")
            line = _obj(physical.get("region")).get("startLine")
            message = _obj(result.get("message")).get("text") or ""
            findings.append(
                {
                    "file": uri,
                    "line": (line if isinstance(line, int) else 1) if uri else 0,
                    "message": f"{result.get('ruleId') or '?'}: {message}",
                }
            )
    return findings


def cmd_sarif(args: list[str]) -> int:
    """Write a failed scanner step's verdict from the SARIF report it wrote (gitleaks, semgrep)."""
    parser = _verdict_parser("sarif", default_lane="")
    parser.add_argument("report", type=Path)
    opts = parser.parse_args(args)
    if not opts.lane:
        parser.error("--lane is required")
    if not opts.report.is_file():
        report(
            opts.lane,
            Status.ERROR,
            f"the scanner failed and wrote no SARIF report at {opts.report}",
            advice=["It died before scanning — its own step output says why."],
            out_dir=opts.out,
        )
        return 0
    findings = _sarif_findings(json.loads(opts.report.read_text()))
    if findings:
        report(
            opts.lane,
            Status.FAIL,
            f"{len(findings)} finding(s) in {opts.report.name}",
            findings=findings,
            out_dir=opts.out,
        )
    else:
        report(
            opts.lane,
            Status.ERROR,
            f"the scanner failed but {opts.report.name} lists no result",
            advice=["Its own step output says why it exited non-zero."],
            out_dir=opts.out,
        )
    return 0


# ---------------------------------------------------------------------------
# step-outcomes
#
# A job that runs several independent checks (ci.yml's lint-node, lint-python,
# lint-mixed and scan) marks each check step `continue-on-error: true` so one
# red check does not hide the rest, then calls this with one "<name>=<outcome>"
# pair per step. Outcome values are GitHub's own step outcomes: success,
# failure, cancelled, skipped. A check is skipped by its own `if:` — its
# language untouched, or its last pass on this PR reused — and that is a pass,
# exactly as the gate reads a skipped job. A setup step that fails skips every
# check after it, but it fails the job itself, and the gate reads the job result.
# ---------------------------------------------------------------------------

PASSING_OUTCOMES = frozenset({"success", "skipped"})


def _outcome_pairs(pairs: list[str]) -> list[tuple[str, str]]:
    return [(name, outcome) for name, _, outcome in (pair.partition("=") for pair in pairs)]


def cmd_step_outcomes(args: list[str]) -> int:
    parser = _verdict_parser("step-outcomes", default_lane="")
    parser.add_argument("outcome", nargs="+", metavar="name=outcome")
    parser.add_argument(
        "--reused",
        default="{}",
        help="JSON {check: note} from `reuse-plan`: a skipped check listed here is labelled reused",
    )
    opts = parser.parse_args(args)
    if not opts.lane:
        parser.error("--lane is required")
    reused: dict[str, str] = json.loads(opts.reused or "{}")

    failed: list[str] = []
    for name, outcome in _outcome_pairs(opts.outcome):
        label = f"reused — {reused[name]}" if outcome == "skipped" and name in reused else outcome
        print(f"  {name + ':':<24} {label}")
        if outcome not in PASSING_OUTCOMES:
            failed.append(f"{name} ({outcome or 'no outcome'})")

    if failed:
        # The findings live in each check's own verdict (`verdict.py check`
        # wrote `<lane>/<check>` the moment it failed); the rollup only names them.
        report(
            opts.lane,
            Status.FAIL,
            f"{len(failed)} of {len(opts.outcome)} tool(s) did not pass: {', '.join(failed)}",
            advice=[
                f"Read verdict {opts.lane}/{name.split(' ')[0]} for its findings."
                for name in failed
            ],
            out_dir=opts.out,
        )
        return 1
    ran = [name for name, outcome in _outcome_pairs(opts.outcome) if outcome == "success"]
    report(
        opts.lane,
        Status.PASS,
        f"{len(ran)} of {len(opts.outcome)} check(s) ran and passed; the rest had nothing to check or were reused",
        out_dir=opts.out,
    )
    return 0


# ---------------------------------------------------------------------------
# post-statuses
#
# The checks list names jobs, and a grouped job carries a dozen checks: a red
# lint-node says nothing about WHICH of biome, knip or tsc broke. Each check's
# step outcome is posted as its own commit status, `ci / <area> / <check>`,
# linked to the job that ran it; the area makes the PR list sort into groups. A fork's token cannot write statuses, so the workflow skips
# this step there; anywhere else a status that does not land fails the step
# loudly rather than leaving the PR silently short of a check.
# ---------------------------------------------------------------------------

STATUS_CONTEXT_PREFIX = "ci / "
STATUS_AREA_SEPARATOR = " / "


class Area(StrEnum):
    NODE = "node"
    PYTHON = "python"
    CONTRACTS = "contracts"
    TESTS = "tests"
    SECURITY = "security"
    BUILD = "build"


# Every check a grouped job posts. One with no area is refused before anything
# is posted: it would land outside every group.
CHECK_AREAS: dict[str, Area] = {
    **dict.fromkeys(
        (
            "biome",
            "deps",
            "circular",
            "file-size",
            "types-location",
            "doc-comments",
            "components-per-file",
            "duplicates",
            "package-hygiene",
            "type-check",
            "pnpm-audit",
            "dead-code",
        ),
        Area.NODE,
    ),
    **dict.fromkeys(
        (
            "ruff",
            "mypy",
            "mypy-api",
            "mypy-shared",
            "mypy-voice-agent",
            "custom-lints",
            "lint-imports",
            "bandit",
            "xenon",
            "interrogate",
            "plr-complexity",
            "ignore-whys",
            "ignore-staleness",
            "suppression-hygiene",
            "typed-boundaries",
            "uv-lock",
            "tool-pins",
            "import-cost",
        ),
        Area.PYTHON,
    ),
    **dict.fromkeys(
        (
            "api-schema",
            "api-schema-types",
            "analytics-catalog",
            "cli-config-schema",
            "deploy-templates",
            "selfhost-bundle-lock",
            "analytics-sync",
            "analytics-check",
            "observability-evlog-tests",
            "observability-map",
            "observability-ratchet",
            "observability-bots",
            "wide-event-conformance",
            "alert-rules",
        ),
        Area.CONTRACTS,
    ),
    **dict.fromkeys(("test-typescript", "harness-tests", "go-connect"), Area.TESTS),
    **dict.fromkeys(("gitleaks", "semgrep", "trivy", "pip-audit"), Area.SECURITY),
    **dict.fromkeys(("build", "seo"), Area.BUILD),
}


def status_context(check: str) -> str:
    """Return the commit status context a check posts under; KeyError for a check with no area."""
    return f"{STATUS_CONTEXT_PREFIX}{CHECK_AREAS[check]}{STATUS_AREA_SEPARATOR}{check}"


def _check_of_context(context: str) -> str | None:
    """Return the check a `ci / <area> / <check>` context names, or None for any other context."""
    if not context.startswith(STATUS_CONTEXT_PREFIX):
        return None
    area, separator, check = context.removeprefix(STATUS_CONTEXT_PREFIX).partition(
        STATUS_AREA_SEPARATOR
    )
    return check if separator and CHECK_AREAS.get(check) == area else None


# The status API rejects a longer description.
STATUS_DESCRIPTION_LIMIT = 140
# Step outcome -> (commit status state, description).
OUTCOME_STATUS: dict[str, tuple[str, str]] = {
    "success": ("success", "passed"),
    "failure": ("failure", "failed — open the job's step of the same name"),
    "cancelled": ("error", "cancelled before it finished"),
    "skipped": ("success", "skipped — nothing it checks changed"),
}
_UNKNOWN_OUTCOME = ("error", "reported no outcome")


def _this_job_url(gh: GitHub, repo: str, run_id: int, attempt: int) -> str | None:
    """Return the html_url of the in-progress job on this runner, or None when no single job is."""
    jobs = gh.collect(
        f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", "jobs"
    )
    runner = os.environ.get("RUNNER_NAME", "")
    mine = [
        job
        for job in jobs
        if job.get("runner_name") == runner and job.get("status") == "in_progress"
    ]
    return field_of(mine[0], "html_url", str) if len(mine) == 1 else None


def _status_fields(name: str, outcome: str, reused: dict[str, str], url: str) -> dict[str, str]:
    state, description = OUTCOME_STATUS.get(outcome, _UNKNOWN_OUTCOME)
    if outcome == "skipped" and name in reused:
        description = f"reused — {reused[name]}"
    return {
        "state": state,
        "context": status_context(name),
        "description": description[:STATUS_DESCRIPTION_LIMIT],
        "target_url": url,
    }


def cmd_post_statuses(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verdict.py post-statuses")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--sha",
        required=True,
        help="the PR HEAD sha (a pull_request run's github.sha is the merge)",
    )
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--reused", default="{}", help="JSON {check: note} from `reuse-plan`")
    parser.add_argument("outcome", nargs="+", metavar="name=outcome")
    opts = parser.parse_args(args)
    reused: dict[str, str] = json.loads(opts.reused or "{}")
    unmapped = [name for name, _ in _outcome_pairs(opts.outcome) if name not in CHECK_AREAS]
    if unmapped:
        print(
            f"::error::post-statuses: no area for {', '.join(unmapped)} — add each to "
            "CHECK_AREAS in scripts/ci/verdict.py; nothing posted"
        )
        return 1

    gh = GitHub.from_env()
    try:
        url = _this_job_url(gh, opts.repo, opts.run_id, opts.run_attempt)
    except GitHubError as err:
        print(
            f"::error::post-statuses: run {opts.run_id}'s jobs are unreadable ({err}) — nothing posted"
        )
        return 1
    if url is None:
        print(
            f"::error::post-statuses: no single in-progress job of run {opts.run_id} "
            f"runs on {os.environ.get('RUNNER_NAME', '<unset RUNNER_NAME>')} — nothing posted"
        )
        return 1

    endpoint = f"repos/{opts.repo}/statuses/{opts.sha}"
    lost: list[str] = []
    for name, outcome in _outcome_pairs(opts.outcome):
        fields = _status_fields(name, outcome, reused, url)
        try:
            gh.post(endpoint, fields)
        except GitHubError as err:
            print(f"  {fields['context']:<28} not posted: {err}")
            lost.append(fields["context"])
            continue
        print(f"  {fields['context']:<28} {fields['state']:<8} {fields['description']}")
    if lost:
        print(f"::error::post-statuses: {len(lost)} status(es) never landed: {', '.join(lost)}")
        return 1
    return 0


# ---------------------------------------------------------------------------
# reuse-plan
#
# A push used to re-run every check its PR touched against the base, even when
# the push changed nothing a check reads: the last commit on #1307 touched four
# Python files and still rebuilt the web app, re-ran knip, jscpd and the TS
# checks. A check's last PASS on this PR still holds when nx would not select
# its task (the lane table's `nx`) for what changed between that pass's head and
# this one, head and base both: the same answer detect gates the check on, so a
# file the check reads, its config and the CI harness all rerun it. `detect`
# computes the plan, each reusable step skips on it, and `step-outcomes` reads
# the skip as a pass. Anything unreadable means no reuse: the only safe
# direction here is running more.
#
# A pass is read from the check's own `ci / <area> / <check>` status (posted by
# `post-statuses`), never from the job API: a `continue-on-error` step that
# FAILED reports conclusion `success` there, so a red check read as an anchor.
# The status's target_url names the run that posted it, which is how the plan
# finds the base tip that run recorded.
# ---------------------------------------------------------------------------

LANES_FILE = REPO_ROOT / "scripts" / "dev" / "verify-lanes.json"

REUSE_LOOKBACK_RUNS = 30
# The annotation each run's plan leaves on its `detect` job naming the base tip
# it validated, so a later run can diff base movement too: a pull_request run
# checks the MERGE of head and base, and the base moves between pushes.
VALIDATED_BASE_TITLE = "reuse-plan base"
DETECT_JOB = "detect"
# A status that proves the check passed: it ran green, or it was itself reused
# from a pass whose scope has not moved since.
PROVEN_DESCRIPTION = re.compile(r"^(passed|reused)\b")


def _check_tasks(lanes_file: Path) -> dict[str, str]:
    """Map each reusable check to the nx task that decides it; a check with no task always runs."""
    return {
        lane["ci_check"]: lane["nx"]
        for lane in json.loads(lanes_file.read_text())["lanes"]
        if lane.get("ci_check") and lane.get("nx")
    }


def _affected_tasks(changed: list[str]) -> dict[str, list[dict[str, str]]]:
    """Return the nx tasks a set of changed files reaches, each with why."""
    return nx_affected.select(["--files", *changed]).tasks if changed else {}


def _changed_between(anchor: str, head: str) -> list[str] | None:
    """Paths changed from anchor to head, or None when either commit is not in the checkout."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{anchor}..{head}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        print(f"  git diff {anchor[:12]}..{head[:12]} failed: {proc.stderr.strip()}")
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _validated_base(head_sha: str) -> str | None:
    """Return the base tip this pull_request checkout merged the head into, or None when HEAD is not that merge."""
    proc = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    commits = proc.stdout.split()
    if proc.returncode != 0 or len(commits) != 3 or head_sha not in commits[1:]:
        return None
    return next(parent for parent in commits[1:] if parent != head_sha)


def _recorded_base(gh: GitHub, job: Json) -> str | None:
    """Return the base tip an earlier run's plan annotated on its detect job, if it left one."""
    url = text_of(job, "check_run_url")
    if "api.github.com/" not in url:
        return None
    for note in gh.get_list(f"{url.split('api.github.com/', 1)[1]}/annotations"):
        if note.get("title") == VALIDATED_BASE_TITLE:
            return str(note.get("message", "")).strip() or None
    return None


def _proven_checks(gh: GitHub, repo: str, sha: str, run_id: int) -> set[str]:
    """Return the checks whose LATEST status on sha is a pass that run `run_id` posted."""
    combined = gh.get(f"repos/{repo}/commits/{sha}/status?per_page=100")
    proven: set[str] = set()
    for status in records(combined, "statuses"):
        check = _check_of_context(str(status.get("context", "")))
        if (
            check is not None
            and status.get("state") == "success"
            and PROVEN_DESCRIPTION.match(str(status.get("description", "")))
            and f"/actions/runs/{run_id}/" in str(status.get("target_url", ""))
        ):
            proven.add(check)
    return proven


class _Anchor(NamedTuple):
    run_id: int
    head_sha: str
    base_sha: str


class _PrRuns(NamedTuple):
    """Which runs to read: this PR's earlier runs of one workflow, against one base branch."""

    repo: str
    workflow: str
    branch: str
    base: str
    run_id: int


def _run_jobs(gh: GitHub, repo: str, run_id: int) -> list[Json]:
    return gh.collect(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", "jobs")


def _base_refs(run: Json) -> set[object]:
    return {
        base.get("ref")
        for entry in records(run, "pull_requests")
        if isinstance(base := entry.get("base"), dict)
    }


def _reuse_anchors(gh: GitHub, pr: _PrRuns, wanted: set[str]) -> dict[str, _Anchor]:
    """Each check's newest earlier PASS on this PR (same base branch, recorded base tip)."""
    listing = gh.get(
        f"repos/{pr.repo}/actions/workflows/{pr.workflow}/runs"
        f"?branch={pr.branch}&event=pull_request&per_page={REUSE_LOOKBACK_RUNS}"
    )
    anchors: dict[str, _Anchor] = {}
    for run in records(listing, "workflow_runs"):
        run_id = field_of(run, "id", int)
        if run_id == pr.run_id or run.get("status") != "completed":
            continue
        if pr.base not in _base_refs(run):
            continue
        head_sha = field_of(run, "head_sha", str)
        passed = (_proven_checks(gh, pr.repo, head_sha, run_id) & wanted) - set(anchors)
        if not passed:
            continue
        detect = next(
            (job for job in _run_jobs(gh, pr.repo, run_id) if job.get("name") == DETECT_JOB), None
        )
        recorded = _recorded_base(gh, detect) if detect else None
        if recorded:
            for check in passed:
                anchors[check] = _Anchor(run_id, head_sha, recorded)
        if len(anchors) == len(wanted):
            break
    return anchors


def _reuse_note(
    check: str,
    task: str,
    anchor: _Anchor | None,
    affected: dict[tuple[str, str], dict[str, list[dict[str, str]]] | None],
) -> str | None:
    """Return why `check` is reused, or None (printing why it runs)."""
    if anchor is None:
        print(f"  {check + ':':<28} runs — no earlier pass on this PR")
        return None
    reached = affected[(anchor.head_sha, anchor.base_sha)]
    if reached is None:
        print(f"  {check + ':':<28} runs — run {anchor.run_id}'s commits are not in the checkout")
        return None
    if task in reached:
        why = reached[task][0]
        print(
            f"  {check + ':':<28} runs — {why.get('file') or why['kind']} changed since run {anchor.run_id}"
        )
        return None
    note = (
        f"passed at {anchor.head_sha[:12]} in run {anchor.run_id}; nothing it reads changed since"
    )
    print(f"  {check + ':':<28} REUSED — {note}")
    return note


def _affected_since(
    anchors: dict[str, _Anchor], head_sha: str, current_base: str
) -> dict[tuple[str, str], dict[str, list[dict[str, str]]] | None]:
    """Ask nx once per anchor what changed since it, on the head and the base; None when undiffable."""
    out: dict[tuple[str, str], dict[str, list[dict[str, str]]] | None] = {}
    for anchor in anchors.values():
        key = (anchor.head_sha, anchor.base_sha)
        if key in out:
            continue
        head_changes = _changed_between(anchor.head_sha, head_sha)
        base_changes = _changed_between(anchor.base_sha, current_base)
        out[key] = (
            None
            if head_changes is None or base_changes is None
            else _affected_tasks(sorted(set(head_changes + base_changes)))
        )
    return out


def cmd_reuse_plan(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verdict.py reuse-plan")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--workflow", required=True, help="the workflow file name, e.g. ci.yml")
    parser.add_argument("--branch", required=True, help="the PR head branch")
    parser.add_argument(
        "--base", required=True, help="the PR base branch this run validates against"
    )
    parser.add_argument(
        "--head-sha", required=True, help="the PR HEAD sha (github.sha is the merge commit)"
    )
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", type=int, default=1, help="a manual re-run reuses nothing")
    parser.add_argument("--event", required=True)
    parser.add_argument("--lanes", type=Path, default=LANES_FILE)
    opts = parser.parse_args(args)

    reused: dict[str, str] = {}
    current_base = _validated_base(opts.head_sha) if opts.event == "pull_request" else None
    if current_base:
        print(f"::notice title={VALIDATED_BASE_TITLE}::{current_base}")
    if current_base is None or opts.run_attempt > 1:
        print(
            f"reuse-plan: {opts.event} attempt {opts.run_attempt}, validated base "
            f"{current_base or 'unknown'} — every check runs"
        )
    else:
        tasks = _check_tasks(opts.lanes)
        try:
            anchors = _reuse_anchors(
                GitHub.from_env(),
                _PrRuns(opts.repo, opts.workflow, opts.branch, opts.base, opts.run_id),
                set(tasks),
            )
        except GitHubError as err:
            # Unreadable means no proof of an earlier pass; running more is the safe side.
            print(f"reuse-plan: earlier runs are unreadable ({err}) — every check runs")
            anchors = {}
        affected = _affected_since(anchors, opts.head_sha, current_base)
        for check in sorted(tasks):
            note = _reuse_note(check, tasks[check], anchors.get(check), affected)
            if note:
                reused[check] = note

    outputs = os.environ.get("GITHUB_OUTPUT")
    if outputs:
        with Path(outputs).open("a") as handle:
            handle.write(f"reused_checks={json.dumps(sorted(reused))}\n")
            handle.write(f"reused={json.dumps(reused)}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and reused:
        rows = "\n".join(f"| `{check}` | {note} |" for check, note in sorted(reused.items()))
        with Path(summary).open("a") as handle:
            handle.write(f"### Reused checks\n\n| check | why |\n| --- | --- |\n{rows}\n")
    print(f"reuse-plan: {len(reused)} check(s) reused")
    return 0


SUBCOMMANDS = {
    "emit": cmd_emit,
    "consolidate": cmd_consolidate,
    "check-ownership": cmd_check_ownership,
    "dir": cmd_dir,
    "pytest-verdict": cmd_pytest_verdict,
    "regression-proof-select": cmd_regression_proof_select,
    "regression-proof-verdict": cmd_regression_proof_verdict,
    "collect": cmd_collect,
    "check": cmd_check,
    "sarif": cmd_sarif,
    "step-outcomes": cmd_step_outcomes,
    "post-statuses": cmd_post_statuses,
    "reuse-plan": cmd_reuse_plan,
}


def main() -> int:
    argv = sys.argv[1:]
    sub = argv[0] if argv else ""
    handler = SUBCOMMANDS.get(sub)
    if handler is None:
        print(f"verdict.py: unknown subcommand '{sub}'", file=sys.stderr)
        print(f"usage: verdict.py <{' | '.join(SUBCOMMANDS)}> [args]", file=sys.stderr)
        return 2
    return handler(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
