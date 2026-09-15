#!/usr/bin/env python3
"""mise ci:remote [branch|PR#] — why this PR is red, in one command.

Prints the PR's gate state and then, for every non-green check, the failure
itself: the lane's machine-readable verdict artifact when the lane uploaded one,
otherwise the relevant tail of the job log (anchored on the last ``##[error]``,
because a GitHub job log ends in post-job cleanup, not in the failure).

Verdict artifacts are downloadable while the run is still in progress; job logs
are not ("logs will be available when it is complete"), which is why the
artifact is the preferred source.

`--watch` polls until checks go terminal (bounded), printing transitions.
`--verbose` adds full finding details, passing lanes, and the source used.
`--json` emits the same report as one object.

Exit codes: 0 = no failed checks and no conflicts (pending is NOT failure);
            1 = at least one failed check or conflicting branch;
            2 = usage/auth/config error.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
import io
import json
import os
import re
import subprocess
import sys
import time
from typing import TypedDict
import zipfile

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from gaia_gh import (
    classify_failure,
    current_branch,
    eprint,
    gh,
    parse_repo,
    resolve_pr,
)

SCHEMA_VERSION = 2
MAX_CHECK_PAGES = 6  # 100/page -> up to 600 check runs; plenty for any PR
MAX_PARALLEL_FETCHES = 8
VERDICT_PREFIX = "verdict-"
FALLBACK_TAIL_LINES = 40  # kept in --json; the human render shows the last SHOWN_TAIL_LINES
SHOWN_TAIL_LINES = 20
DETAIL_PREVIEW_LINES = 3
MAX_CHECK_PAGE_SIZE = 100
FAILING = ("failed", "error", "timeout")
VERDICT_BAD = ("fail", "error", "timed_out")
ERROR_MARK = "ERROR: "
COUNT_KEYS = ("passed", "failed", "pending", "skipped", "error", "timeout")

CONCLUSION_MAP = {
    "success": "passed",
    "failure": "failed",
    "neutral": "skipped",
    "skipped": "skipped",
    "cancelled": "skipped",
    "timed_out": "timeout",
    "action_required": "error",
    "startup_failure": "error",
    "stale": "skipped",
}

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# `gh run view --log` prefixes every line with "job\tstep\ttimestamp ".
RUNVIEW_PREFIX_RE = re.compile(r"^[^\t]*\t[^\t]*\t\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
# `gh api .../jobs/{id}/logs` prefixes every line with an ISO timestamp.
TS_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s?")
NOISE_RE = re.compile(r"^##\[(?:group|endgroup|debug|section|start-action|end-action)\b")
# `test_x PASSED [ 34%]` — pytest's -vv progress. Never why a job went red.
PYTEST_PASS_RE = re.compile(r"\s(?:PASSED|SKIPPED|XFAIL|XPASS)\s+\[\s*\d+%\]$")
RUN_ID_RE = re.compile(r"/actions/runs/(\d+)")
JOB_ID_RE = re.compile(r"/job/(\d+)")
SLUG_RE = re.compile(r"[^a-z0-9]+")
# "Mutation shard 3/6 (21 modules)" — a matrix job renders its 1-based position.
MATRIX_POSITION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
# "verdict-test-mutation-2" — the uploader folds the 0-based matrix value in.
ARTIFACT_INDEX_RE = re.compile(r"-(\d+)$")


class Finding(TypedDict, total=False):
    file: str
    line: int
    message: str
    detail: str


class Verdict(TypedDict, total=False):
    lane: str
    status: str
    summary: str
    findings: list[Finding]
    advice: list[str]
    artifact: str
    run_id: int


class Check(TypedDict):
    name: str
    app: str
    status: str
    url: str | None
    run_id: int | None
    job_id: int | None
    started_at: str | None
    completed_at: str | None


class StackRow(TypedDict):
    branch: str
    pr: int | None
    base: str | None
    expected_base: str
    is_current: bool
    counts: dict[str, int]
    base_mismatch: bool


@dataclass(frozen=True)
class Repo:
    """Where to ask, and how long to wait — the triple every fetch needs."""

    owner: str
    name: str
    timeout_s: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    def api(self, suffix: str) -> str:
        return f"repos/{self.owner}/{self.name}/{suffix}"


@dataclass(frozen=True)
class Options:
    """The flags, parsed and validated once."""

    as_json: bool
    verbose: bool
    watch: bool
    with_stack: bool
    interval: int
    max_wait: int
    timeout_s: int


def gh_bytes(args: list[str], timeout_s: int) -> tuple[int, bytes, str]:
    """`gh` with undecoded stdout — artifact zips and ANSI-laden job logs.

    gaia_gh.gh decodes as text, which mangles a zip; this is the binary twin.
    """
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return 124, b"", f"gh timed out after {timeout_s}s"
    except FileNotFoundError:
        return 127, b"", "gh CLI not found on PATH"
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def slug(text: str) -> str:
    return SLUG_RE.sub("-", text.lower()).strip("-")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def empty_counts() -> dict[str, int]:
    return dict.fromkeys(COUNT_KEYS, 0)


# --------------------------------------------------------------------- PR + check runs


def fetch_pr_state(repo: Repo, pr_number: int) -> dict:
    """One GraphQL round trip: PR meta + review state + unresolved thread count."""
    query = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){ pullRequest(number:$number){
    number title url headRefOid baseRefName headRefName isDraft mergeable reviewDecision
    reviewThreads(first:100){ totalCount nodes{ isResolved } }
  } } }
"""
    payload = json.dumps(
        {"query": query, "variables": {"owner": repo.owner, "name": repo.name, "number": pr_number}}
    )
    rc, out, err = gh(["api", "graphql", "--input", "-"], repo.timeout_s, stdin_text=payload)
    if rc != 0:
        eprint(f"ci:remote: POST /graphql (pull request state) failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    data = json.loads(out)
    if "errors" in data:
        eprint(
            f"ci:remote: GraphQL errors (pull request state): {json.dumps(data['errors'])[:300]}"
        )
        sys.exit(2)
    return data["data"]["repository"]["pullRequest"]


def fetch_check_runs(repo: Repo, head_sha: str) -> tuple[list[dict], bool]:
    """All check runs on the head commit. Returns (runs, truncated)."""
    runs: list[dict] = []
    page = 1
    endpoint = repo.api(f"commits/{head_sha}/check-runs")
    while page <= MAX_CHECK_PAGES:
        rc, out, err = gh(["api", f"{endpoint}?per_page=100&page={page}"], repo.timeout_s)
        if rc != 0:
            eprint(f"ci:remote: GET {endpoint} failed:\n{err.strip()[:400]}")
            sys.exit(classify_failure(err, rc))
        batch = json.loads(out).get("check_runs", [])
        runs.extend(batch)
        if len(batch) < MAX_CHECK_PAGE_SIZE:
            return runs, False
        page += 1
    return runs, True


def normalize(runs: list[dict]) -> list[Check]:
    out: list[Check] = []
    for run in runs:
        completed = run.get("status") == "completed"
        conclusion = run.get("conclusion")
        if not completed or conclusion is None:
            status = "pending"
        else:
            status = CONCLUSION_MAP.get(conclusion, "error")
        url = run.get("html_url") or ""
        run_match = RUN_ID_RE.search(url)
        job_match = JOB_ID_RE.search(url)
        out.append(
            Check(
                name=run.get("name", "?"),
                app=(run.get("app") or {}).get("slug", ""),
                status=status,
                url=run.get("html_url"),
                run_id=int(run_match.group(1)) if run_match else None,
                job_id=int(job_match.group(1)) if job_match else None,
                started_at=run.get("started_at"),
                completed_at=run.get("completed_at"),
            )
        )
    return sorted(
        out,
        key=lambda c: (
            {"failed": 0, "error": 0, "timeout": 0, "pending": 1}.get(c["status"], 2),
            c["name"].lower(),
        ),
    )


# ----------------------------------------------------------------------------- verdicts


def fetch_run_verdicts(repo: Repo, run_id: int) -> list[Verdict]:
    """Every `verdict-*` artifact on a run, unzipped and parsed.

    Artifacts are downloadable while the run is still in progress — unlike job
    logs, which only materialise once the whole run completes.
    """
    endpoint = repo.api(f"actions/runs/{run_id}/artifacts")
    rc, out, err = gh(["api", f"{endpoint}?per_page=100"], repo.timeout_s)
    if rc != 0:
        eprint(f"ci:remote: GET {endpoint} failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    wanted = [
        a
        for a in json.loads(out).get("artifacts", [])
        if a.get("name", "").startswith(VERDICT_PREFIX) and not a.get("expired")
    ]
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FETCHES) as pool:
        blobs = list(pool.map(lambda a: fetch_artifact(repo, a["id"]), wanted))

    verdicts: list[Verdict] = []
    for artifact, blob in zip(wanted, blobs, strict=True):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.namelist():
                if not member.endswith(".json"):
                    continue
                parsed: Verdict = json.loads(archive.read(member))
                parsed["artifact"] = artifact["name"]
                parsed["run_id"] = run_id
                verdicts.append(parsed)
    return verdicts


def fetch_artifact(repo: Repo, artifact_id: int) -> bytes:
    endpoint = repo.api(f"actions/artifacts/{artifact_id}/zip")
    rc, blob, err = gh_bytes(["api", endpoint], repo.timeout_s)
    if rc != 0:
        eprint(f"ci:remote: GET {endpoint} failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    return blob


def matrix_index(check_name: str) -> int | None:
    """0-based matrix position from a check's display name: "3/6" -> 2."""
    match = MATRIX_POSITION_RE.search(check_name)
    if not match:
        return None
    position, total = int(match.group(1)), int(match.group(2))
    return position - 1 if 1 <= position <= total else None


def artifact_index(artifact: str) -> tuple[str, int] | None:
    """Split `verdict-test-mutation-2` into ("test-mutation", 2)."""
    stem = artifact[len(VERDICT_PREFIX) :]
    match = ARTIFACT_INDEX_RE.search(stem)
    return (stem[: match.start()], int(match.group(1))) if match else None


def matches_by_matrix_index(verdict: Verdict, check_name: str) -> bool:
    """A shard's artifact carries no name a shard's check name slugs to.

    `Mutation shard 3/6 (21 modules)` is matrix value 2, and its verdicts ride
    in `verdict-test-mutation-2` — so the per-module findings were stranded as
    "no matching check run" while the check itself fell back to a composite-step
    log tail. The index is the association. A shared word between the artifact
    stem and the check name keeps `verdict-anything-else-2` from claiming it.
    """
    index = matrix_index(check_name)
    parsed = artifact_index(verdict.get("artifact", ""))
    if index is None or parsed is None or parsed[1] != index:
        return False
    stem, _ = parsed
    return bool(set(slug(stem).split("-")) & set(slug(check_name).split("-")))


def verdict_matches(verdict: Verdict, check_name: str) -> bool:
    """A verdict belongs to a check when its lane or artifact name slugs to it.

    A check name carries decoration the artifact name cannot: matrix jobs render
    as `test-python (unit-a)` and sharded ones as `Mutation shard 3/6 (19
    modules)`, so a slug prefix counts — but only on a token boundary, or
    `verdict-lint` would claim `lint-python`.
    """
    target = slug(check_name)
    candidates = (
        slug(verdict.get("lane", "")),
        slug(verdict.get("artifact", "")[len(VERDICT_PREFIX) :]),
    )
    if any(c and (target == c or target.startswith(f"{c}-")) for c in candidates):
        return True
    return matches_by_matrix_index(verdict, check_name)


def explaining_verdicts(check: Check, verdicts: list[Verdict]) -> list[Verdict]:
    """The verdicts on this check that say why it is red.

    A `pass` verdict never explains a red check, and matching one is not
    hypothetical: the mutation shards write `mutation/shard-N` as `pass` before
    the job later fails, and that lane prefix-matches the failing check
    `Mutation shard N/6 (19 modules)`. Printing it put `FAIL … [pass]` in the
    failure section and suppressed the log tail that held the real reason.
    """
    return drop_content_free_rollups(matching_failing_verdicts(check, verdicts))


def matching_failing_verdicts(check: Check, verdicts: list[Verdict]) -> list[Verdict]:
    """Every failing verdict this check owns, rollups included.

    `explaining_verdicts` is what to PRINT; this is what the check accounts
    for. The difference matters to the orphan section: a rollup dropped as
    redundant has still been spoken for, and re-printing it as "no matching
    check run" puts the pointer-to-nothing back on screen.
    """
    return [
        v for v in verdicts if v.get("status") in VERDICT_BAD and verdict_matches(v, check["name"])
    ]


def drop_content_free_rollups(matched: list[Verdict]) -> list[Verdict]:
    """Within one artifact, a verdict with findings supersedes one without.

    A shard uploads both its per-module verdicts and a `mutation/shard-N`
    rollup whose whole summary is "its reason is only in this job's log" —
    which is false once a sibling verdict carries the file:line, and printing
    both buries the answer under a pointer to nothing.
    """
    informative = {v.get("artifact") for v in matched if v.get("findings")}
    return [v for v in matched if v.get("findings") or v.get("artifact") not in informative]


# ----------------------------------------------------------------------------- job logs


def clean_log(raw: str) -> list[str]:
    """Strip the prefixes that make a raw Actions log unreadable.

    Removes ANSI, the per-line ISO timestamp (`gh api .../logs`) or the
    `job\tstep\ttimestamp` prefix (`gh run view --log`), grouping markers and
    blank lines; rewrites `##[error]` as `ERROR: ` so the failure reads as
    English.

    Per-test PASSED/SKIPPED progress lines go too: a `-vv` mutation shard
    prints hundreds of them, and they fill the whole window with tests that
    did not fail. FAILED and ERROR lines are kept.
    """
    lines: list[str] = []
    for raw_line in raw.splitlines():
        line = ANSI_RE.sub("", raw_line)
        line = RUNVIEW_PREFIX_RE.sub("", line)
        line = TS_PREFIX_RE.sub("", line).rstrip()
        if not line.strip() or NOISE_RE.match(line) or PYTEST_PASS_RE.search(line):
            continue
        lines.append(line.replace("##[error]", ERROR_MARK).replace("##[warning]", "WARNING: "))
    return lines


def failure_tail(lines: list[str], limit: int = FALLBACK_TAIL_LINES) -> list[str]:
    """The window ending at the last `ERROR:` line, not at the end of the log.

    A job log's literal tail is post-job cleanup: on a real mutation-shard
    failure the `##[error]` sat 51 lines from the end, so a plain tail showed
    artifact uploads and `git config` calls instead of the failure.
    """
    anchor: int | None = None
    for i, line in enumerate(lines):
        if line.startswith(ERROR_MARK):
            anchor = i
    if anchor is None:
        return lines[-limit:]
    return lines[max(0, anchor + 1 - limit) : anchor + 1]


def fetch_job_tail(repo: Repo, job_id: int) -> list[str]:
    endpoint = repo.api(f"actions/jobs/{job_id}/logs")
    rc, blob, err = gh_bytes(["api", "--allow-escape-sequences", endpoint], repo.timeout_s)
    if rc != 0 and "unknown flag" in err.lower():  # older gh has no such flag
        rc, blob, err = gh_bytes(["api", endpoint], repo.timeout_s)
    if rc != 0:
        if "404" in err or "not found" in err.lower():
            return [f"(no log yet: GET {endpoint} -> 404; logs appear once the run completes)"]
        eprint(f"ci:remote: GET {endpoint} failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    return failure_tail(clean_log(blob.decode("utf-8", "replace")))


# ---------------------------------------------------------------------------- diagnosis


def diagnose(
    repo: Repo, checks: list[Check]
) -> tuple[list[Verdict], dict[str, list[str]], dict[str, str]]:
    """For every failing check: its verdict, else its job-log tail.

    Returns (verdicts, fallback tails by check name, source label by check name).
    """
    failing = [c for c in checks if c["status"] in FAILING]
    if not failing:
        return [], {}, {}

    run_ids = sorted({c["run_id"] for c in failing if c["run_id"] is not None})
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FETCHES) as pool:
        batches = list(pool.map(lambda r: fetch_run_verdicts(repo, r), run_ids))
    verdicts = [v for batch in batches for v in batch]

    # No run-level fallback: "some lane on this run failed" is not an answer to
    # "why is THIS check red". Pointing six mutation shards at python-static's
    # verdict because they share a run is worse than saying nothing, so a check
    # with no verdict of its own goes to its log — including an aggregate job
    # like `Quality gate (required)`, whose log tail is the lane table.
    sources: dict[str, str] = {}
    needs_log: list[Check] = []
    for check in failing:
        explaining = explaining_verdicts(check, verdicts)
        if explaining:
            artifacts = sorted({v.get("artifact", "?") for v in explaining})
            sources[check["name"]] = f"verdict artifact {', '.join(artifacts)}"
        elif check["job_id"] is None:
            sources[check["name"]] = (
                f"external check ({check['app'] or 'unknown app'}) — open the URL"
            )
        else:
            needs_log.append(check)

    tails: dict[str, list[str]] = {}
    if needs_log:
        job_ids = [c["job_id"] for c in needs_log]
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FETCHES) as pool:
            fetched = list(pool.map(lambda j: fetch_job_tail(repo, j or 0), job_ids))
        for check, tail in zip(needs_log, fetched, strict=True):
            tails[check["name"]] = tail
            sources[check["name"]] = (
                "no failing verdict in this run's artifacts — log tail"
                if check["run_id"] in {v.get("run_id") for v in verdicts}
                else "lane uploaded no verdict artifact — log tail"
            )
    return verdicts, tails, sources


# -------------------------------------------------------------------------------- stack


def fetch_stack(repo: Repo) -> dict | None:
    """`gh stack view --json`, or None when the branch is not in a stack.

    Never `gh stack view` bare — without `--json` it opens a TUI that hangs
    under a PTY.
    """
    try:
        proc = subprocess.run(
            ["gh", "stack", "view", "--json"],
            capture_output=True,
            text=True,
            timeout=repo.timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None  # 2 = not in a stack; anything else = extension absent
    return json.loads(proc.stdout)


def fetch_stack_states(repo: Repo, numbers: list[int]) -> dict[int, dict]:
    """One GraphQL for every stack PR's base branch + check rollup."""
    if not numbers:
        return {}
    aliases = " ".join(
        f"p{n}: pullRequest(number:{n}){{ number baseRefName "
        "commits(last:1){nodes{commit{statusCheckRollup{contexts(first:100){nodes{"
        "__typename ... on CheckRun{conclusion status} ... on StatusContext{state}"
        "}}}}}} }"
        for n in numbers
    )
    query = (
        f"query($owner:String!,$name:String!){{repository(owner:$owner,name:$name){{{aliases}}}}}"
    )
    payload = json.dumps({"query": query, "variables": {"owner": repo.owner, "name": repo.name}})
    rc, out, err = gh(["api", "graphql", "--input", "-"], repo.timeout_s, stdin_text=payload)
    if rc != 0:
        eprint(f"ci:remote: POST /graphql (stack rollups) failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    data = json.loads(out)
    if "errors" in data:
        eprint(f"ci:remote: GraphQL errors (stack rollups): {json.dumps(data['errors'])[:300]}")
        sys.exit(2)
    repository = data["data"]["repository"] or {}
    return {pr["number"]: pr for pr in repository.values() if pr is not None}


def rollup_counts(pr_state: dict) -> dict[str, int]:
    counts = empty_counts()
    commits = (pr_state.get("commits") or {}).get("nodes") or []
    if not commits:
        return counts
    rollup = commits[0]["commit"].get("statusCheckRollup") or {}
    for node in (rollup.get("contexts") or {}).get("nodes", []):
        if node.get("__typename") == "CheckRun":
            raw = node.get("conclusion") if node.get("status") == "COMPLETED" else None
        else:
            raw = {"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure"}.get(
                node.get("state", "")
            )
        counts[CONCLUSION_MAP.get((raw or "").lower(), "pending") if raw else "pending"] += 1
    return counts


def build_stack(repo: Repo, payload: dict) -> list[StackRow]:
    branches = payload.get("branches") or []
    trunk = payload.get("trunk") or "master"
    numbers = [b["pr"]["number"] for b in branches if b.get("pr")]
    states = fetch_stack_states(repo, numbers)
    rows: list[StackRow] = []
    for i, entry in enumerate(branches):
        expected = trunk if i == 0 else branches[i - 1]["name"]
        number = entry["pr"]["number"] if entry.get("pr") else None
        state = states.get(number) if number else None
        base = (state or {}).get("baseRefName")
        rows.append(
            StackRow(
                branch=entry["name"],
                pr=number,
                base=base,
                expected_base=expected,
                is_current=bool(entry.get("isCurrent")),
                counts=rollup_counts(state) if state else empty_counts(),
                base_mismatch=bool(base and base != expected),
            )
        )
    return rows


# ---------------------------------------------------------------------------- rendering


def header(report: dict) -> None:
    pr = report["pr"]
    counts = report["counts"]
    draft = "  [DRAFT]" if pr["is_draft"] else ""
    print(f"PR #{pr['number']} {pr['title']}{draft}")
    print(
        f"  base {pr['base']} | {pr['mergeable']} | "
        f"review: {pr['review_decision'] or 'none yet'} | "
        f"{plural(report['unresolved_thread_count'], 'unresolved thread')}"
    )
    failed = counts["failed"] + counts["error"] + counts["timeout"]
    print(
        f"  checks: {counts['passed']} pass / {failed} fail / "
        f"{counts['pending']} pending / {counts['skipped']} skipped"
        + ("  [TRUNCATED >600 checks]" if report["truncated"] else "")
    )


def render_verdict(verdict: Verdict, verbose: bool, pad: str = "  ") -> None:
    """A verdict's body: its summary, then every finding at file:line."""
    if verdict.get("summary"):
        print(f"{pad}{verdict['summary']}")
    for finding in verdict.get("findings", []):
        where = finding.get("file", "?")
        if finding.get("line") is not None:
            where = f"{where}:{finding['line']}"
        print(f"{pad}{where} — {finding.get('message', '')}")
        detail = (finding.get("detail") or "").splitlines()
        if not detail:
            continue
        for detail_line in detail if verbose else detail[:DETAIL_PREVIEW_LINES]:
            print(f"{pad}    {detail_line}")
        if not verbose and len(detail) > DETAIL_PREVIEW_LINES:
            print(f"{pad}    … {len(detail) - DETAIL_PREVIEW_LINES} more lines (--verbose)")


def render_log_tail(report: dict, check: Check, source: str, verbose: bool) -> None:
    print(f"FAIL  {check['name']}  [{check['status']}]  ({source})")
    tail = report["fallback_tails"].get(check["name"], [])
    shown = tail if verbose else tail[-SHOWN_TAIL_LINES:]
    if len(tail) > len(shown):
        print(f"  … {len(tail) - len(shown)} earlier lines (--verbose)")
    for line in shown:
        print(f"  {line}")
    if not tail:
        print(f"  {check['url']}")


def render_failing_check(report: dict, check: Check, verbose: bool) -> set[str]:
    """Render one red check. Returns the lane slugs it accounted for."""
    source = report["sources"].get(check["name"], "")
    matched = explaining_verdicts(check, report["verdicts"])
    if not matched:
        render_log_tail(report, check, source, verbose)
    else:
        print(f"FAIL  {check['name']}  [{check['status']}]  ({source})")
        for verdict in matched:
            lane = verdict.get("lane", "?")
            if slug(lane) == slug(check["name"]):
                render_verdict(verdict, verbose, pad="  ")
            else:
                print(f"  {lane}  [{verdict.get('status', '?')}]")
                render_verdict(verdict, verbose, pad="    ")
    if verbose and check["url"]:
        print(f"  source: {source} | {check['url']}")
    print()
    return {slug(v.get("lane", "")) for v in matching_failing_verdicts(check, report["verdicts"])}


def render_failures(report: dict, verbose: bool) -> None:
    printed: set[str] = set()
    for check in report["checks"]:
        if check["status"] in FAILING:
            printed |= render_failing_check(report, check, verbose)

    for verdict in report["verdicts"]:
        if verdict.get("status") in VERDICT_BAD and slug(verdict.get("lane", "")) not in printed:
            print("(verdict with no matching check run — a lane failed inside a passing job)")
            print(f"FAIL  {verdict.get('lane', '?')}  [{verdict.get('status', '?')}]")
            render_verdict(verdict, verbose)
            print()


def render_pending(report: dict) -> None:
    pending = [c["name"] for c in report["checks"] if c["status"] == "pending"]
    for name in pending:
        print(f"PEND  {name}")
    if pending:
        print()


def render_stack(rows: list[StackRow], current_pr: int) -> None:
    if not rows:
        return
    print("STACK")
    width = max(len(r["branch"]) for r in rows)
    for row in rows:
        counts = row["counts"]
        marker = "*" if row["pr"] == current_pr else " "
        summary = (
            f"{counts['passed']} pass / {counts['failed']} fail / {counts['pending']} pending"
            if row["pr"]
            else "no PR"
        )
        number = f"#{row['pr']}" if row["pr"] else "#----"
        print(f" {marker} {number} {row['branch']:<{width}}  -> {row['base'] or '?'}  {summary}")
        if row["base_mismatch"]:
            print(
                f"     WARNING: GitHub base is '{row['base']}' but the stack parent is "
                f"'{row['expected_base']}' — every diff-scoped gate (mutation, test-impact, "
                "diff-cover) is scoped against the wrong branch."
            )
    print()


def collect_advice(report: dict, branch: str) -> list[str]:
    advice: list[str] = []
    failing = [v for v in report["verdicts"] if v.get("status") in VERDICT_BAD]
    for verdict in drop_content_free_rollups(failing):
        advice.extend(verdict.get("advice", []))
    pr = report["pr"]
    counts = report["counts"]
    if pr["mergeable"] == "CONFLICTING":
        advice.append(f"Merge conflicts with '{pr['base']}' — `git merge origin/{pr['base']}`.")
    if report["unresolved_thread_count"]:
        advice.append(
            f"{plural(report['unresolved_thread_count'], 'unresolved review thread')}: "
            f"`mise pr:comments {branch}`."
        )
    if counts["pending"]:
        advice.append(
            f"{plural(counts['pending'], 'check')} still running: "
            f"`mise ci:remote --watch {branch}`."
        )
    red = [c["name"] for c in report["checks"] if c["status"] in FAILING]
    if red and not any(v.get("status") in VERDICT_BAD for v in report["verdicts"]):
        advice.append(
            f"{plural(len(red), 'lane')} failed with no verdict artifact — the tails above are "
            "all GitHub has. Give the lane a verdict (.github/actions/upload-verdict) "
            "so the next reader gets file:line."
        )
    if pr["review_decision"] == "CHANGES_REQUESTED":
        advice.append("A reviewer requested changes — address them, then re-request review.")
    for row in report["stack"]:
        if row["base_mismatch"]:
            advice.append(
                f"Retarget #{row['pr']} onto '{row['expected_base']}': "
                f"`gh pr edit {row['pr']} --base {row['expected_base']}`."
            )
    deduped: list[str] = []
    for line in advice:
        if line not in deduped:
            deduped.append(line)
    return deduped


def render(report: dict, verbose: bool) -> None:
    header(report)
    print()
    render_failures(report, verbose)
    render_pending(report)
    render_stack(report["stack"], report["pr"]["number"])
    if report["advice"]:
        print("ADVICE")
        for line in report["advice"]:
            print(f"  - {line}")
    else:
        print("ADVICE\n  - Nothing blocking on GitHub's side. Merge per team policy.")

    if verbose:
        print("\nPASSING")
        for check in report["checks"]:
            if check["status"] not in FAILING and check["status"] != "pending":
                print(f"  {check['status']:<8}{check['name']}")


# ------------------------------------------------------------------------------- driver


def snapshot_once(repo: Repo, pr_number: int, branch: str, with_stack: bool) -> tuple[dict, int]:
    t0 = time.monotonic()
    pr_meta = fetch_pr_state(repo, pr_number)
    runs, truncated = fetch_check_runs(repo, pr_meta["headRefOid"])
    checks = normalize(runs)
    counts = {k: sum(1 for c in checks if c["status"] == k) for k in COUNT_KEYS}
    verdicts, tails, sources = diagnose(repo, checks)

    stack_payload = fetch_stack(repo) if with_stack else None
    stack_rows = build_stack(repo, stack_payload) if stack_payload else []

    unresolved = sum(1 for t in pr_meta["reviewThreads"]["nodes"] if not t["isResolved"])
    thread_total = pr_meta["reviewThreads"]["totalCount"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "repo": repo.slug,
        "pr": {
            "number": pr_number,
            "title": pr_meta["title"],
            "url": pr_meta["url"],
            "head_sha": pr_meta["headRefOid"],
            "base": pr_meta["baseRefName"],
            "head": pr_meta["headRefName"],
            "mergeable": pr_meta["mergeable"],
            "review_decision": pr_meta["reviewDecision"],
            "is_draft": bool(pr_meta["isDraft"]),
        },
        "checks": checks,
        "verdicts": verdicts,
        "fallback_tails": tails,
        "sources": sources,
        "stack": stack_rows,
        "unresolved_thread_count": unresolved,
        "thread_count_total": thread_total,
        "threads_truncated": thread_total > 100,
        "counts": counts,
        "truncated": truncated,
        "fetched_at": datetime.now(UTC).isoformat(),
        "durationMs": int((time.monotonic() - t0) * 1000),
    }
    report["advice"] = collect_advice(report, branch)
    red = counts["failed"] or counts["error"] or counts["timeout"]
    return report, (1 if (red or pr_meta["mergeable"] == "CONFLICTING") else 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Why this PR is red, in one command.")
    parser.add_argument(
        "branch", nargs="?", default=None, help="branch or PR number (default: current branch)"
    )
    parser.add_argument("--json", action="store_true", help="emit only the JSON report")
    parser.add_argument(
        "--verbose", action="store_true", help="full finding details + passing lanes"
    )
    parser.add_argument("--watch", action="store_true", help="poll until checks are terminal")
    parser.add_argument("--no-stack", action="store_true", help="skip the gh stack section")
    parser.add_argument(
        "--interval",
        default=os.environ.get("GAIA_CI_INTERVAL", "30"),
        help="seconds between polls in --watch (default 30)",
    )
    parser.add_argument(
        "--max-wait",
        default=os.environ.get("GAIA_CI_MAX_WAIT", "1800"),
        help="max total seconds to poll in --watch (default 1800)",
    )
    parser.add_argument(
        "--timeout",
        default=os.environ.get("GAIA_PR_TIMEOUT", "45"),
        help="per-network-call timeout seconds (default 45)",
    )
    return parser


def parse_options(args: argparse.Namespace) -> Options:
    """Validate the three duration flags together; exit 2 on any bad one."""
    durations = {
        "--timeout": args.timeout,
        "--interval": args.interval,
        "--max-wait": args.max_wait,
    }
    parsed: dict[str, int] = {}
    for label, raw in durations.items():
        try:
            parsed[label] = int(raw)
        except ValueError:
            eprint(f"usage error: {label} must be an integer, got {raw!r}")
            sys.exit(2)
        if parsed[label] <= 0:
            eprint(f"usage error: {label} must be >= 1")
            sys.exit(2)
    return Options(
        as_json=args.json,
        verbose=args.verbose,
        watch=args.watch,
        with_stack=not args.no_stack,
        interval=parsed["--interval"],
        max_wait=parsed["--max-wait"],
        timeout_s=parsed["--timeout"],
    )


def watch(repo: Repo, pr_number: int, branch: str, options: Options) -> tuple[dict, int]:
    """Poll until no check is pending or the budget runs out."""
    deadline = time.monotonic() + options.max_wait
    poll = 0
    while True:
        poll += 1
        report, exit_code = snapshot_once(repo, pr_number, branch, options.with_stack)
        pending = report["counts"]["pending"]
        if not options.as_json:
            elapsed = int(time.monotonic() - (deadline - options.max_wait))
            print(
                f"watch[{poll}] {datetime.now(UTC).strftime('%H:%M:%S')}: "
                f"{report['counts']['failed']} failed, {pending} pending "
                f"(elapsed {elapsed}s / max {options.max_wait}s)"
            )
        if pending == 0 or time.monotonic() + options.interval > deadline:
            if pending and not options.as_json:
                print(f"watch: stopped after {options.max_wait}s with {pending} still pending.")
            break
        time.sleep(options.interval)
    if not options.as_json:
        print()
    return report, exit_code


def main() -> int:
    args = build_parser().parse_args()
    options = parse_options(args)
    owner, name = parse_repo()
    repo = Repo(owner, name, options.timeout_s)
    branch = args.branch or current_branch()

    resolved = resolve_pr(repo.slug, branch, options.timeout_s)
    if resolved is None:
        print(f"ci:remote: no open PR for '{branch}' — push first or check the branch name.")
        return 0
    pr_number, _, _ = resolved

    if options.watch:
        report, exit_code = watch(repo, pr_number, branch, options)
    else:
        report, exit_code = snapshot_once(repo, pr_number, branch, options.with_stack)

    if options.as_json:
        print(json.dumps(report, indent=2))
    else:
        render(report, options.verbose)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
