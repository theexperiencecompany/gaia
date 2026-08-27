#!/usr/bin/env python3
"""Shared GitHub/gh plumbing for GAIA's agent-legible dev tools.

Used by pr_comments.py and ci_remote.py. Kept dependency-free (stdlib only)
and importable without side effects.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


def gh(args: list[str], timeout_s: int, stdin_text: str | None = None) -> tuple[int, str, str]:
    """Run `gh`; return (returncode, stdout, stderr). Never raises on nonzero."""
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
    """Exit triad for network tools: 1 = auth/network/state-of-transport, 2 = usage/config."""
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


def resolve_pr(repo_slug: str, branch: str, timeout_s: int) -> tuple[int, str, str] | None:
    """branch -> (number, url, head_sha); None if no open PR (state, not an error)."""
    rc, out, err = gh(
        ["pr", "view", branch, "--repo", repo_slug, "--json", "number,url,headRefOid"], timeout_s
    )
    if rc != 0:
        if "no pull requests found" in err.lower() or "no open pull requests" in err.lower():
            return None
        eprint(f"gh failed resolving the PR:\n{err.strip()[:400]}")
        sys.exit(classify_failure(err, rc))
    meta = json.loads(out)
    return meta["number"], meta["url"], meta["headRefOid"]
