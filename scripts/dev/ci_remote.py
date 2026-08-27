#!/usr/bin/env python3
"""mise ci:remote [branch] — the merge-readiness dashboard for a PR's GitHub side.

One command answers "what stands between this branch and merge?":
  - every check run on the head commit (passed/failed/pending/skipped)
  - mergeability (conflicts?), review decision (approved? changes requested?), draft
  - unresolved review-thread count (cross-ref: `mise pr:comments` for the threads)

`--watch` polls until checks go terminal (bounded), printing transitions.

Exit codes: 0 = no failed checks and no conflicts (pending is NOT failure — read counts);
            1 = at least one failed check or conflicting branch;
            2 = usage/auth/config error.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import sys
import time

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from gaia_gh import (
    classify_failure,
    current_branch,
    eprint,
    gh,
    parse_repo,
    resolve_pr,
)

SCHEMA_VERSION = 1
MAX_CHECK_PAGES = 6  # 100/page -> up to 600 check runs; plenty for any PR
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


def step(n: int, total: int, msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"[{n}/{total}] {msg}", flush=True)


def fetch_snapshot(owner: str, name: str, pr_number: int, timeout_s: int) -> dict:
    """One GraphQL round trip: PR meta + review state + unresolved thread count."""
    query = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){ pullRequest(number:$number){
    headRefOid url isDraft mergeable reviewDecision
    reviewThreads(first:100){ totalCount nodes{ isResolved } }
  } } }
"""
    payload = json.dumps(
        {"query": query, "variables": {"owner": owner, "name": name, "number": pr_number}}
    )
    rc, out, err = gh(["api", "graphql", "--input", "-"], timeout_s, stdin_text=payload)
    if rc != 0:
        eprint(f"ci:remote: GraphQL fetch failed:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    data = json.loads(out)
    if "errors" in data:
        eprint(f"ci:remote: GraphQL errors: {json.dumps(data['errors'])[:300]}")
        sys.exit(2)
    return data["data"]["repository"]["pullRequest"]


def fetch_check_runs(
    owner: str, name: str, head_sha: str, timeout_s: int
) -> tuple[list[dict], bool]:
    """All check runs on the head commit. Returns (runs, truncated)."""
    runs: list[dict] = []
    page = 1
    while page <= MAX_CHECK_PAGES:
        rc, out, err = gh(
            ["api", f"repos/{owner}/{name}/commits/{head_sha}/check-runs?per_page=100&page={page}"],
            timeout_s,
        )
        if rc != 0:
            eprint(f"ci:remote: check-runs fetch failed:\n{err.strip()[:400]}")
            sys.exit(classify_failure(err, rc))
        batch = json.loads(out).get("check_runs", [])
        runs.extend(batch)
        if len(batch) < 100:
            return runs, False
        page += 1
    return runs, True


def normalize(runs: list[dict]) -> list[dict]:
    out = []
    for r in runs:
        completed = r.get("status") == "completed"
        conclusion = r.get("conclusion")
        if not completed or conclusion is None:
            status = "pending"
        else:
            status = CONCLUSION_MAP.get(conclusion, "error")
        out.append(
            {
                "name": r.get("name", "?"),
                "app": (r.get("app") or {}).get("slug", ""),
                "status": status,
                "url": r.get("html_url"),
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
            }
        )
    return sorted(
        out,
        key=lambda c: (
            {"failed": 0, "error": 0, "timeout": 0, "pending": 1}.get(c["status"], 2),
            c["name"].lower(),
        ),
    )


def render(
    checks: list[dict],
    counts: dict[str, int],
    pr_number: int,
    duration_ms: int,
    truncated: bool,
) -> None:
    print(
        f"\nci:remote #{pr_number}: {len(checks)} checks — "
        f"{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['pending']} pending, {counts['skipped']} skipped"
        + (
            f", {counts['timeout']} timeout, {counts['error']} error"
            if (counts["timeout"] or counts["error"])
            else ""
        )
        + f" [{duration_ms} ms]"
        + ("  ⚠ TRUNCATED (>600 checks)" if truncated else "")
    )
    for c in checks:
        if c["status"] in ("failed", "error", "timeout"):
            print(f"  FAIL  {c['name']}  {c['url']}")
    for c in checks:
        if c["status"] == "pending":
            print(f"  PEND  {c['name']}")


def next_steps(pr_meta: dict, unresolved: int, counts: dict[str, int], branch: str) -> None:
    mergeable = pr_meta.get("mergeable")
    review_decision = pr_meta.get("reviewDecision")
    steps: list[str] = []
    if mergeable == "CONFLICTING":
        steps.append(
            "Branch has merge conflicts with master — merge/rebase origin/master into it and resolve."
        )
    if unresolved > 0:
        steps.append(
            f"{unresolved} unresolved review thread(s): run `mise pr:comments {branch}` for the full list + resolution syntax."
        )
    if counts["failed"] or counts["error"] or counts["timeout"]:
        steps.append("Fix the failing checks above; their links point at the run logs.")
    if counts["pending"]:
        steps.append(
            f"{counts['pending']} check(s) still running: re-run `mise ci:remote --watch {branch}` to poll until terminal."
        )
    if review_decision == "CHANGES_REQUESTED":
        steps.append("A reviewer has requested changes — address them, then re-request review.")
    elif review_decision == "REVIEW_REQUIRED":
        steps.append("Approval required before merge (policy: humans merge, agents never do).")
    if (
        mergeable == "MERGEABLE"
        and unresolved == 0
        and not counts["failed"]
        and not counts["error"]
        and not counts["timeout"]
        and not counts["pending"]
        and review_decision in ("APPROVED", None)
    ):
        steps.append(
            "All clear locally-known state: checks green, no conflicts, approved. Merge per team policy."
        )
    if steps:
        print("\nNEXT STEPS:")
        for s_ in steps:
            print(f"  - {s_}")
    else:
        print("\nNEXT: nothing actionable surfaced.")


def snapshot_once(
    owner: str,
    name: str,
    pr_number: int,
    gh_timeout: int,
    quiet_json: bool,
    branch: str,
    show_next: bool = True,
    quiet_human: bool = False,
) -> tuple[dict, int]:
    t0 = time.monotonic()
    quiet_all = quiet_json or quiet_human
    step(1, 2, f"fetching PR state + review threads for #{pr_number} …", quiet_all)
    pr_meta = fetch_snapshot(owner, name, pr_number, gh_timeout)
    step(2, 2, "fetching check runs on head sha …", quiet_all)
    runs, truncated = fetch_check_runs(owner, name, pr_meta["headRefOid"], gh_timeout)
    checks = normalize(runs)
    counts = {
        k: sum(1 for c in checks if c["status"] == k)
        for k in ("passed", "failed", "pending", "skipped", "error", "timeout")
    }
    unresolved = sum(1 for t in pr_meta["reviewThreads"]["nodes"] if not t["isResolved"])
    thread_total = pr_meta["reviewThreads"]["totalCount"]
    duration_ms = int((time.monotonic() - t0) * 1000)

    report = {
        "schema_version": SCHEMA_VERSION,
        "repo": f"{owner}/{name}",
        "pr": {
            "number": pr_number,
            "url": pr_meta["url"],
            "head_sha": pr_meta["headRefOid"],
            "mergeable": pr_meta["mergeable"],
            "review_decision": pr_meta["reviewDecision"],
            "is_draft": bool(pr_meta["isDraft"]),
        },
        "checks": checks,
        "unresolved_thread_count": unresolved,
        "thread_count_total": thread_total,
        "threads_truncated": thread_total > 100,
        "counts": counts,
        "truncated": truncated,
        "fetched_at": datetime.now(UTC).isoformat(),
        "durationMs": duration_ms,
    }

    if not quiet_all:
        render(checks, counts, pr_number, duration_ms, truncated)
        draft_txt = " [DRAFT]" if pr_meta["isDraft"] else ""
        print(
            f"PR STATE: mergeable={pr_meta.get('mergeable')} | "
            f"review={pr_meta.get('reviewDecision') or 'none yet'}{draft_txt}"
            f" | unresolved_threads={unresolved}/{thread_total}"
        )
        if show_next:
            next_steps(pr_meta, unresolved, counts, branch)
    return report, (
        1
        if (
            counts["failed"]
            or counts["error"]
            or counts["timeout"]
            or pr_meta["mergeable"] == "CONFLICTING"
        )
        else 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge-readiness dashboard for a PR's GitHub gates."
    )
    parser.add_argument("branch", nargs="?", default=None, help="branch (default: current)")
    parser.add_argument("--json", action="store_true", help="emit only the JSON report")
    parser.add_argument("--watch", action="store_true", help="poll until checks are terminal")
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
    args = parser.parse_args()

    try:
        gh_timeout = int(args.timeout)
        interval = int(args.interval)
        max_wait = int(args.max_wait)
    except ValueError:
        eprint("usage error: --timeout/--interval/--max-wait must be integers")
        sys.exit(2)
    for label, v in (("--timeout", gh_timeout), ("--interval", interval), ("--max-wait", max_wait)):
        if v <= 0:
            eprint(f"usage error: {label} must be >= 1")
            sys.exit(2)

    owner, name = parse_repo()
    repo_slug = f"{owner}/{name}"
    branch = args.branch or current_branch()
    resolved = resolve_pr(repo_slug, branch, gh_timeout)
    if resolved is None:
        print(f"ci:remote: no open PR for branch '{branch}' — push first or check the branch name.")
        return 0
    pr_number, _, _ = resolved

    if not args.watch:
        report, exit_code = snapshot_once(owner, name, pr_number, gh_timeout, args.json, branch)
        if args.json:
            print(json.dumps(report, indent=2))
        return exit_code

    # watch mode: bounded polling with transition lines
    deadline = time.monotonic() + max_wait
    poll = 0
    while True:
        poll += 1
        report, exit_code = snapshot_once(
            owner,
            name,
            pr_number,
            gh_timeout,
            args.json,
            branch,
            show_next=False,
            quiet_human=True,
        )
        counts = report["counts"]
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        elapsed = int(time.monotonic() - (deadline - max_wait))
        if not args.json:
            print(
                f"  watch[{poll}] {stamp}: {counts['failed']} failed, "
                f"{report['counts']['pending']} pending (elapsed {elapsed}s / max {max_wait}s)"
            )
        if report["counts"]["pending"] == 0 or time.monotonic() + interval > deadline:
            if not args.json:
                if report["counts"]["pending"]:
                    print(
                        f"  watch: stopping after {max_wait}s with "
                        f"{report['counts']['pending']} still pending — re-run later."
                    )
            break
        time.sleep(interval)
    if not args.json:
        # terminal iteration: full verdict + guidance now
        render(
            report["checks"],
            report["counts"],
            report["pr"]["number"],
            report["durationMs"],
            report["truncated"],
        )
        draft_txt = " [DRAFT]" if report["pr"]["is_draft"] else ""
        print(
            f"PR STATE: mergeable={report['pr']['mergeable']} | "
            f"review={report['pr']['review_decision'] or 'none yet'}{draft_txt}"
            f" | unresolved_threads={report['unresolved_thread_count']}/{report['thread_count_total']}"
        )
        next_steps(
            {
                "mergeable": report["pr"]["mergeable"],
                "reviewDecision": report["pr"]["review_decision"],
            },
            report["unresolved_thread_count"],
            report["counts"],
            branch,
        )

    if args.json:
        print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
