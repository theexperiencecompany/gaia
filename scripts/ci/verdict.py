#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
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
         [--out DIR] [--only-if-missing]
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
    collect --into <findings.jsonl>
        Read mypy/tsc/ruff/biome/bandit output on stdin and append its
        file:line findings to a JSONL that `step-outcomes` folds into the
        lane's one verdict. Prints nothing — annotating here too would put
        every finding on the page twice.
    step-outcomes --lane L [--findings F] [--out DIR] <name>=<outcome> [...]
        Fail a job when any of its `continue-on-error` steps did not pass,
        naming every one that did not.
    mirror-previous-gate --repo R --sha S --workflow W --job J --run-id N
        Repeat what the LAST completed run of this workflow concluded for this
        same head SHA. The gate calls it on a PR edit that moved no code: it
        must not re-run the lanes (nothing changed) and it must not skip
        either, because a skipped required check counts as passing.

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
import shutil
import subprocess
import sys
from typing import Any, NamedTuple, NotRequired, TypedDict

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
    """The verdict directory when no `--out` says otherwise."""
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


class Finding(TypedDict):
    """One concrete thing a reader can go fix, at the line it is on."""

    file: str
    line: int
    message: str
    detail: NotRequired[str]


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


def write_verdict(doc: VerdictDoc, out_dir: Path) -> Path:
    path = verdict_path(doc["lane"], out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return path


def _summary_block(doc: VerdictDoc) -> str:
    status = doc["status"]
    lines = [f"### {doc['lane']} — {status}", "", doc["summary"], ""]
    for finding in doc["findings"]:
        lines.append(f"- `{finding['file']}:{finding['line']}` {finding['message']}")
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


def announce(doc: VerdictDoc) -> None:
    """Annotate every finding, append the step-summary block, print the verdict.

    All three, or none — forgetting one of them separately is the bug this
    whole module exists to make impossible.
    """
    status = Status(doc["status"])
    level = ANNOTATION_LEVEL[status]
    for finding in doc["findings"]:
        print(
            f"::{level} file={finding['file']},line={finding['line']}::"
            f"{_escape(finding['message'])}"
        )

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
    """The flags every verdict-producing subcommand shares."""
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
    """Write one lane's verdict. Exits 0 even for a failure — it reports, it does
    not decide; `ci_verdict_die` is the call site that dies on one."""
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
        findings=findings,
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
    many there are is decided at runtime (by the matrix, by `mutation.sh plan`),
    so the gate expects the family and is satisfied by at least one member —
    a per-shard `--expect` list in YAML would drift from the planner on the
    first large diff.
    """
    return sorted(k for k in found if _belongs(k, family))


def _missing_members(lane: str, family: str, matched: list[str], planned: str) -> list[Row]:
    """Return the row a family owes when fewer members reported than were planned.

    `<job>@<family>*<n>` is how the runtime size of a matrix reaches the gate —
    `mutation.sh plan` already emits the shard count it packed the diff into.
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
    """The table rows one `--expect` entry produces, and nothing else.

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
# mutation shards pass `mutation`, because mutation.sh writes one verdict per
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
    opts = parser.parse_args(args)

    found = _load_verdicts(opts.directory) if opts.directory.is_dir() else {}
    rows = consolidated_rows(opts.expect, found)

    print("::group::Per-lane verdicts")
    for lane, status, summary in rows:
        print(f"  {lane + ':':<28} {status!s:<10} {summary}")
    print("::endgroup::")

    bad = [(lane, status, summary) for lane, status, summary in rows if status in FAILING_STATUSES]
    for lane, status, summary in bad:
        print(f"::error::{lane}: {str(status).upper()} — {_escape(summary)}")
        doc = found.get(lane)
        for finding in doc["findings"] if doc else []:
            print(f"    {finding['file']}:{finding['line']}  {finding['message']}")

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
    """Test node ids in ``source``; with ``marked_only`` just those carrying the
    regression mark — on the function, on its class, on the module's
    ``pytestmark``, or on one of its ``pytest.param`` cases (pytest's ``-m``
    then narrows the run to the marked cases)."""
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
                # The tail, not the head: pytest puts the assertion and the
                # exception at the END of the traceback, which is what a reader
                # opens the detail for.
                detail="\n".join(text.splitlines()[-40:]),
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
# collect
#
# Turn mypy/tsc/ruff/biome/bandit output into findings for the lane's verdict.
# ---------------------------------------------------------------------------

ANNOTATION_PATTERNS = [
    # mypy: path:line: error: msg  or path:line:col: error
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)?\s*(?:error|warning):"),
    # tsc: path(line,col): error TS...
    re.compile(r"^(?P<file>[^\(]+)\((?P<line>\d+),(?P<col>\d+)\):\s*error"),
    # ruff concise: path:line:col: CODE msg
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\d+:\s*[A-Z]+\d+\s"),
    # biome concise: path:line:col lint/category
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)\s"),
]


def cmd_collect(args: list[str]) -> int:
    """Append stdin's file:line findings to a JSONL the lane's verdict will carry.

    It deliberately prints NOTHING. Annotating here and emitting the verdict
    later would put every finding on the page twice; the lane's single `emit`
    is the one producer, and this is how a tool's own output reaches it.
    """
    parser = argparse.ArgumentParser(prog="verdict.py collect")
    parser.add_argument("--into", type=Path, required=True)
    opts = parser.parse_args(args)

    found: list[Finding] = []
    for line in sys.stdin:
        for pattern in ANNOTATION_PATTERNS:
            match = pattern.match(line.strip())
            if match:
                found.append(
                    {
                        "file": match.group("file").strip(),
                        "line": int(match.group("line")),
                        "message": line.strip()[:500],
                    }
                )
                break
    opts.into.parent.mkdir(parents=True, exist_ok=True)
    with opts.into.open("a") as handle:
        handle.writelines(json.dumps(f) + "\n" for f in found)
    return 0


# ---------------------------------------------------------------------------
# step-outcomes
#
# A job that runs several independent tools (see code-quality.yml's
# python-static lane) marks each tool step `continue-on-error: true` so one red
# tool does not hide the rest, then calls this with one "<name>=<outcome>" pair
# per step. Outcome values are GitHub's own step outcomes: success, failure,
# cancelled, skipped.
# ---------------------------------------------------------------------------


def cmd_step_outcomes(args: list[str]) -> int:
    parser = _verdict_parser("step-outcomes", default_lane="")
    parser.add_argument("outcome", nargs="+", metavar="name=outcome")
    parser.add_argument(
        "--findings",
        type=Path,
        help="JSONL written by `verdict.py collect` — the tools' own file:line findings",
    )
    opts = parser.parse_args(args)
    if not opts.lane:
        parser.error("--lane is required")

    failed: list[str] = []
    for pair in opts.outcome:
        name, _, outcome = pair.partition("=")
        print(f"  {name + ':':<16} {outcome}")
        if outcome != "success":
            failed.append(f"{name} ({outcome})")

    findings: list[Finding] = []
    if opts.findings and opts.findings.exists():
        findings = [json.loads(line) for line in opts.findings.read_text().splitlines() if line]

    if failed:
        report(
            opts.lane,
            Status.FAIL,
            f"{len(failed)} of {len(opts.outcome)} tool(s) did not pass: {', '.join(failed)}",
            findings=findings,
            advice=[
                f"Expand the '{name.split(' ')[0]}' group above for its output." for name in failed
            ],
            out_dir=opts.out,
        )
        return 1
    report(opts.lane, Status.PASS, f"all {len(opts.outcome)} tools passed", out_dir=opts.out)
    return 0


# ---------------------------------------------------------------------------
# mirror-previous-gate
#
# `pull_request: edited` is carried for RETARGETS, which re-scope every lane
# against the new base. It fires for a title or body edit too, and those move
# no code, so the lane DAG is guarded to skip them. The GATE may not skip with
# it: branch protection reads a skipped required check as PASSING, so the edit
# run's skipped gate becomes the head SHA's latest verdict and a PR whose last
# real run was RED turns mergeable on a typo fix. So the gate always runs, and
# on that edit it repeats the verdict this same head SHA already earned.
# ---------------------------------------------------------------------------

# A gate job that did not conclude has no verdict to mirror. `skipped` is what
# every run older than this subcommand left behind on an edit, and it is
# precisely the value that must never read as a pass.
NO_VERDICT_CONCLUSIONS = frozenset({None, "skipped"})


def _gh_json(endpoint: str) -> dict[str, Any] | None:
    """`gh api <endpoint>` decoded, or None when gh or the API fails."""
    if shutil.which("gh") is None:
        print("  gh is not on PATH")
        return None
    proc = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"  gh api {endpoint} failed: {proc.stderr.strip()}")
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"  gh api {endpoint} returned no JSON")
        return None


def _gate_conclusion(repo: str, run_id: int, job_name: str) -> str | None:
    """Return what that run's gate job concluded, or None if it never concluded."""
    jobs = _gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
    for job in (jobs or {}).get("jobs", []):
        if job.get("name") != job_name:
            continue
        conclusion = job.get("conclusion")
        return None if conclusion in NO_VERDICT_CONCLUSIONS else str(conclusion)
    return None


def cmd_mirror_previous_gate(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="verdict.py mirror-previous-gate")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--sha",
        required=True,
        help=(
            "the PR HEAD sha, not github.sha — a pull_request run's github.sha is the "
            "merge commit, while the check runs branch protection reads hang off the head"
        ),
    )
    parser.add_argument("--workflow", required=True, help="this workflow's file name")
    parser.add_argument("--job", required=True, help="the gate job's `name:`")
    parser.add_argument("--run-id", required=True, type=int, help="this run, excluded")
    opts = parser.parse_args(args)

    listing = _gh_json(
        f"repos/{opts.repo}/actions/workflows/{opts.workflow}/runs?head_sha={opts.sha}&per_page=50"
    )
    if listing is None:
        print(f"::error::quality-gate: could not read the runs for {opts.sha} — nothing to mirror")
        return 1

    # Newest first, as the API returns them.
    for run in listing.get("workflow_runs", []):
        run_id = int(run["id"])
        if run_id == opts.run_id or run.get("status") != "completed":
            continue
        conclusion = _gate_conclusion(opts.repo, run_id, opts.job)
        if conclusion is None:
            continue
        if conclusion == "success":
            print(f"quality-gate: PASSED — mirroring run {run_id}, which concluded success")
            return 0
        print(
            f"::error::quality-gate: run {run_id} concluded {conclusion} for this commit, and "
            "this edit changed no code. Fix the failures and push, or re-run that run."
        )
        return 1

    print(
        f"::error::quality-gate: no completed run of {opts.workflow} has decided {opts.sha} yet, "
        "so there is no verdict to mirror. Re-run this gate once the lanes finish."
    )
    return 1


SUBCOMMANDS = {
    "emit": cmd_emit,
    "consolidate": cmd_consolidate,
    "check-ownership": cmd_check_ownership,
    "dir": cmd_dir,
    "pytest-verdict": cmd_pytest_verdict,
    "regression-proof-select": cmd_regression_proof_select,
    "regression-proof-verdict": cmd_regression_proof_verdict,
    "collect": cmd_collect,
    "step-outcomes": cmd_step_outcomes,
    "mirror-previous-gate": cmd_mirror_previous_gate,
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
