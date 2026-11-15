#!/usr/bin/env python3
"""Shared plumbing for GAIA's agent-legible dev tools that read GitHub.

Used by ci_remote.py, pr_comments.py and pr_conflicts.py. Every API call goes
through scripts/ci/lib/github.py, so the importer puts scripts/ci on sys.path
first. Stdlib only and importable without side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
import re
import subprocess
import sys

from lib.github import GitHub, GitHubError, Json, field_of, records

# 1 = auth or an outage that outlasted the retries; any other permanent API error is 2.
AUTH_FAILURES = frozenset({HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN})
PR_NUMBER_RE = re.compile(r"#?(\d+)")
# gh pr view's own window: the newest PRs ever opened from the branch.
BRANCH_PR_WINDOW = 30

PR_BY_NUMBER_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){ pullRequest(number:$number){ number url headRefOid } } }
"""
PRS_BY_BRANCH_QUERY = f"""
query($owner:String!,$name:String!,$branch:String!){{
  repository(owner:$owner,name:$name){{
    pullRequests(headRefName:$branch,states:[OPEN,CLOSED,MERGED],first:{BRANCH_PR_WINDOW},
                 orderBy:{{field:CREATED_AT,direction:DESC}}){{
      nodes{{ number url headRefOid state }} }} }} }}
"""


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head_sha: str


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


def exit_code(err: GitHubError) -> int:
    return 1 if err.transient or err.status in AUTH_FAILURES else 2


def current_branch() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        eprint("usage error: not inside a git repository")
        sys.exit(2)
    branch = proc.stdout.strip()
    if branch == "HEAD":
        eprint("usage error: detached HEAD — pass a branch name explicitly")
        sys.exit(2)
    return branch


def parse_repo() -> tuple[str, str]:
    """owner, name from the origin remote."""
    proc = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        eprint("usage error: not inside a git repository")
        sys.exit(2)
    match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", proc.stdout.strip())
    if not match:
        eprint("usage error: cannot parse owner/repo from origin remote")
        sys.exit(2)
    owner, name = match.group(1).split("/")
    return owner, name


def _pull_request(node: Json) -> PullRequest:
    return PullRequest(
        field_of(node, "number", int), field_of(node, "url", str), field_of(node, "headRefOid", str)
    )


def resolve_pr(github: GitHub, owner: str, name: str, selector: str) -> PullRequest | None:
    """Find the PR a number names, or a branch's open PR else its newest closed one, as gh pr view does.

    None when the branch never had a PR (state, not an error).
    """
    variables: dict[str, object] = {"owner": owner, "name": name}
    if number := PR_NUMBER_RE.fullmatch(selector):
        variables["number"] = int(number.group(1))
        repo = field_of(github.graphql(PR_BY_NUMBER_QUERY, variables), "repository", dict)
        return _pull_request(field_of(repo, "pullRequest", dict))
    variables["branch"] = selector
    repo = field_of(github.graphql(PRS_BY_BRANCH_QUERY, variables), "repository", dict)
    nodes = records(field_of(repo, "pullRequests", dict), "nodes")
    if not nodes:
        return None
    return _pull_request(next((n for n in nodes if n.get("state") == "OPEN"), nodes[0]))
