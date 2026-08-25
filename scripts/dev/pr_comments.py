#!/usr/bin/env python3
"""mise pr:comments — fetch GitHub PR review threads as structured, sanitized output.

Read-only by design: this tool NEVER resolves, replies, or mutates. It hands you
the exact IDs and command syntax to do those actions deliberately.

The two ID spaces both matter (mined failure mode #1):
  - `id`          : GraphQL global id (PRRT_…)   -> required by resolveReviewThread
  - `database_id` : REST numeric id             -> required by the replies REST route
(both come straight from GraphQL: global `id` + `databaseId` — one API, zero joins).

Usage:
  mise pr:comments [branch] [--json] [--raw] [--timeout N]

Output contract (JSON, additive-only):
  {schema_version, repo, pr{number,url,head_sha}, threads:[{id, database_id|null,
   path, line, author, is_bot, is_resolved, is_outdated, body_excerpt,
   body_truncated, raw_body?, replies_count}], thread_count, unresolved_count,
   outdated_unresolved_count, truncated, fetched_at, durationMs}

Exit codes: 0 = fetched (review state lives in unresolved_count, not exit code);
            1 = auth/network failure talking to GitHub;
            2 = usage/config error.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import html
import json
import os
import re
import subprocess
import sys
import time

SCHEMA_VERSION = 1
KNOWN_BOTS = {
    "coderabbitai",
    "greptile-apps",
    "greptile",
    "claude",
    "github-actions",
    "sonarqube-cloud",
    "sonarcloud-update",
    "renovate",
    "dependabot",
    "netlify",
}
GRAPHQL_PAGE = 50
MAX_GRAPHQL_PAGES = 20
MAX_REST_PAGES = 20
EXCERPT_LIMIT = 500


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


def step(n: int, total: int, msg: str, quiet: bool) -> None:
    if not quiet:
        print(f"[{n}/{total}] {msg}", flush=True)


def gh(args: list[str], timeout_s: int, stdin_text: str | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["gh", *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"gh timed out after {timeout_s}s"
    except FileNotFoundError:
        return 127, "", "gh CLI not found on PATH"


def classify_failure(stderr: str, returncode: int) -> int:
    """Map a gh failure to our exit triad: 1 auth/network, 2 usage/config."""
    low = stderr.lower()
    authish = any(
        m in low
        for m in (
            "bad credentials",
            "unauthorized",
            "forbidden",
            "rate limit",
            "could not resolve host",
            "timed out",
            "token",
            "api rate",
        )
    )
    return 1 if (authish or returncode in (4, 124)) else 2


def parse_repo() -> tuple[str, str]:
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
    ).stdout.strip()
    match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        sys.exit("usage error: cannot parse owner/repo from origin remote")
    owner, name = match.group(1).split("/")
    return owner, name


IMPERSONATION_RE = re.compile(
    r"^\s*(next steps\b|next:|verify:|pr:comments)", re.IGNORECASE | re.MULTILINE
)


def sanitize_body(body: str) -> tuple[str, bool, bool]:
    """Return (excerpt, truncated, redacted_agent_prompt).

    Hardened against the mined attack class (CA-E3): bot bodies carrying
    terminal escapes and forged tool-guidance lines. Strips C0/C1 control
    chars, drops <details> blocks wholesale (bot boilerplate lives there),
    and masks anything shape-matching this tool's own guidance so a hostile
    body cannot forge instructions above our genuine NEXT STEPS.
    """
    redacted = False
    details_blocks = re.findall(r"(?is)<details[^>]*>.*?</details>", body)
    for block in details_blocks:
        if re.search(
            r"prompt for ai agents|instructions? for (automated )?agents|ai agents",
            block,
            flags=re.IGNORECASE,
        ):
            redacted = True
    if details_blocks:
        body = re.sub(
            r"(?is)<details[^>]*>.*?</details>", "[collapsed details block - view on GitHub]", body
        )
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = "".join(
        ch if (ch in ("\n", "\t") or (ord(ch) >= 32 and not (127 <= ord(ch) <= 159))) else "\n"
        for ch in text
    )
    text = IMPERSONATION_RE.sub("[tool-impersonation line redacted]", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    truncated = len(text) > EXCERPT_LIMIT
    return (text[:EXCERPT_LIMIT] + ("…" if truncated else "")), truncated, redacted


def is_bot(login: str | None) -> bool:
    if not login:
        return False
    return login.lower().endswith("[bot]") or login.lower() in KNOWN_BOTS


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PR review threads (read-only).")
    parser.add_argument(
        "branch", nargs="?", default=None, help="branch whose PR to inspect (default: current)"
    )
    parser.add_argument("--json", action="store_true", help="emit only the JSON report on stdout")
    parser.add_argument(
        "--raw", action="store_true", help="include unsanitized bodies (raw_body field)"
    )
    parser.add_argument(
        "--timeout",
        default=os.environ.get("GAIA_PR_TIMEOUT", "45"),
        help="per-network-call timeout seconds (default 45)",
    )
    args = parser.parse_args()

    try:
        gh_timeout = int(args.timeout)
    except ValueError:
        eprint(f"usage error: --timeout/GAIA_PR_TIMEOUT must be an integer, got {args.timeout!r}")
        sys.exit(2)
    if gh_timeout <= 0:
        eprint(f"usage error: --timeout must be >= 1 second, got {gh_timeout}")
        sys.exit(2)

    t0 = time.monotonic()
    steps_total = 3
    owner, name = parse_repo()
    repo_slug = f"{owner}/{name}"

    branch = args.branch
    if not branch:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            eprint("usage error: not inside a git repository")
            sys.exit(2)
        branch = proc.stdout.strip()
        if branch == "HEAD":
            eprint("usage error: detached HEAD — pass a branch name explicitly")
            sys.exit(2)

    step(1, steps_total, f"resolving PR for branch '{branch}' …", args.json)
    rc, out, err = gh(
        ["pr", "view", branch, "--repo", repo_slug, "--json", "number,url,headRefOid"], gh_timeout
    )
    if rc != 0:
        if "no pull requests found" in err.lower() or "no open pull requests" in err.lower():
            if args.json:
                print(
                    json.dumps(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "repo": repo_slug,
                            "pr": None,
                            "threads": [],
                            "thread_count": 0,
                            "unresolved_count": 0,
                            "reason": f"no open PR for branch '{branch}'",
                        }
                    )
                )
            else:
                print(f"pr:comments: no open PR for branch '{branch}' — nothing to fetch.")
            return 0
        eprint(f"pr:comments: gh failed resolving the PR:\n{err.strip()[:400]}")
        return classify_failure(err, rc)
    try:
        meta = json.loads(out)
        pr_number, pr_url, head_sha = meta["number"], meta["url"], meta["headRefOid"]
    except (json.JSONDecodeError, KeyError) as exc:
        eprint(f"ci error: gh returned unparseable PR metadata ({exc}): {out[:200]}")
        sys.exit(2)

    step(2, steps_total, f"fetching review threads for #{pr_number} …", args.json)
    query = """
query($owner:String!,$name:String!,$number:Int!,$after:String) {
  repository(owner:$owner,name:$name){ pullRequest(number:$number){
    reviewThreads(first:__FIRST__,after:$after){ pageInfo{hasNextPage endCursor}
      nodes{ id isResolved isOutdated path line originalLine startLine diffSide
        comments(first:3){ totalCount
          nodes{ id databaseId author{ login } body } } } } } } }
""".replace("__FIRST__", str(GRAPHQL_PAGE))
    threads_raw: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        payload = json.dumps(
            {
                "query": query,
                "variables": {"owner": owner, "name": name, "number": pr_number, "after": cursor},
            }
        )
        rc, out, err = gh(["api", "graphql", "--input", "-"], gh_timeout, stdin_text=payload)
        if rc != 0:
            eprint(f"pr:comments: GraphQL fetch failed:\n{err.strip()[:400]}")
            return classify_failure(err, rc)
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            eprint(f"ci error: gh returned non-JSON GraphQL output ({exc}): {out[:200]}")
            sys.exit(2)
        if "errors" in data:
            eprint(f"pr:comments: GraphQL errors: {json.dumps(data['errors'])[:400]}")
            return 2
        conn = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads_raw.extend(conn["nodes"])
        pages += 1
        if not conn["pageInfo"]["hasNextPage"] or pages >= MAX_GRAPHQL_PAGES:
            truncated = bool(conn["pageInfo"]["hasNextPage"])
            break
        cursor = conn["pageInfo"]["endCursor"]
        step(2, steps_total, f"fetching review threads page {pages + 1} …", args.json)

    step(3, steps_total, "sanitizing bodies …", args.json)
    threads_out: list[dict] = []
    for th in threads_raw:
        comments_conn = th.get("comments", {}) or {}
        comments = comments_conn.get("nodes", []) or []
        first = comments[0] if comments else {}
        author = (first.get("author") or {}).get("login") or "ghost"
        body = first.get("body", "")
        excerpt, trunc, redacted = sanitize_body(body)
        first_db = next(
            (c.get("databaseId") for c in comments if c.get("databaseId") is not None), None
        )
        replies_count = max(0, comments_conn.get("totalCount", 1) - 1)
        entry: dict = {
            "id": th["id"],
            "database_id": first_db,
            "path": th.get("path"),
            "line": th.get("line") or th.get("originalLine"),
            "start_line": th.get("originalStartLine") or th.get("startLine"),
            "author": author,
            "is_bot": is_bot(author),
            "is_resolved": th["isResolved"],
            "is_outdated": th["isOutdated"],
            "body_excerpt": excerpt,
            "body_truncated": trunc,
            "replies_count": replies_count,
            "action": ("reply-and-resolve" if th["isOutdated"] else "code-fix-then-resolve"),
        }
        if redacted:
            entry["agent_prompt_redacted"] = True
        if args.raw:
            entry["raw_body"] = body
        threads_out.append(entry)

    unresolved = [t for t in threads_out if not t["is_resolved"]]
    outdated_unresolved = [t for t in unresolved if t["is_outdated"]]
    duration_ms = int((time.monotonic() - t0) * 1000)

    report = {
        "schema_version": SCHEMA_VERSION,
        "repo": repo_slug,
        "pr": {"number": pr_number, "url": pr_url, "head_sha": head_sha},
        "threads": threads_out,
        "thread_count": len(threads_out),
        "unresolved_count": len(unresolved),
        "outdated_unresolved_count": len(outdated_unresolved),
        "truncated": truncated,
        "pages_fetched": pages,
        "fetched_at": datetime.now(UTC).isoformat(),
        "durationMs": duration_ms,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(
        f"\npr:comments #{pr_number}: {len(threads_out)} threads, "
        f"{len(unresolved)} unresolved "
        f"({len(outdated_unresolved)} outdated — the commented line no longer exists in the current diff) "
        f"[{duration_ms} ms]" + ("  ⚠ TRUNCATED — raise limits" if truncated else "")
    )
    for t in unresolved:
        if t["path"] and t.get("start_line") and t["line"] and t["start_line"] != t["line"]:
            loc = f"{t['path']}:{t['start_line']}-{t['line']}"
        elif t["path"] and t["line"]:
            loc = f"{t['path']}:{t['line']}"
        elif t["path"]:
            loc = f"{t['path']}"
        else:
            loc = "(no file anchor)"
        flags = "".join(
            [(t["is_bot"] and " [bot]") or "", (t["is_outdated"] and " [outdated]") or ""]
        )
        action = (
            "reply-and-resolve (commented line already changed in a later push — no new code needed)"
            if t["is_outdated"]
            else "fix code first, then reply/resolve (comment applies to your diff)"
        )
        trunc_tag = " [BODY TRUNCATED]" if t["body_truncated"] else ""
        print(f"  • {loc} {flags} ({t['author']}){trunc_tag} {t['body_excerpt'][:160]}")
        print(f"      ACTION: {action}")
        print(f"      ids: database_id={t['database_id']}  thread_node_id={t['id']}")

    if unresolved:
        print(
            "\nNEXT STEPS — use the ids printed above each thread (database_id ↔ <database_id>, thread_node_id ↔ <thread_node_id>):"
        )
        print("  1. Do each thread's ACTION.")
        print("  2. Reply using that thread's database_id:")
        print(
            f"     gh api repos/{repo_slug}/pulls/{pr_number}/comments/<database_id>/replies -f body='your response'"
        )
        print("""  3. ⚠ Resolve ONLY after your fix is pushed and CI is green — resolving early hides unfinished work:
     gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<thread_node_id>"}){thread{isResolved}}}'""")
        print(
            f"  4. Re-run `mise pr:comments {branch}` until it reports 0 unresolved — then confirm threads"
        )
        print("     actually show resolved on the GitHub PR before merging.")
        print(f"  5. GitHub gates: `mise ci:remote {branch}` (checks, conflicts, approvals).")
        print("  (this tool is read-only: it never resolves or replies for you)")
    else:
        print("NEXT: no unresolved threads — check CI before merging: gh pr checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
