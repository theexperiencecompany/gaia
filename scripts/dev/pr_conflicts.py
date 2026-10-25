#!/usr/bin/env python3
"""mise pr:conflicts — which open PRs will conflict once the merge queue lands them in turn.

The queue builds each PR on top of the ones ahead of it, so two PRs that edit the
same lines eject the second no matter how green each is alone. For every pair this
replays the queue (master + A, then + B) with git merge-tree, which writes no
working-tree files and touches no branch.

Usage:
  mise pr:conflicts [PR ...]   default: your open, non-draft PRs

Exit codes: 0 = every PR and pair merges cleanly; 1 = a conflict; 2 = usage/git error.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import combinations
import json
import subprocess
import sys

from gaia_gh import eprint, gh

BASE_BRANCH = "master"
GH_TIMEOUT_S = 30
PR_REF_PREFIX = "refs/pr-conflicts"


@dataclass(frozen=True)
class Merge:
    """A replayed merge: the commit it produced, or the files it conflicted on."""

    commit: str | None
    conflicts: tuple[str, ...]


def git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, cwd=cwd)


def merge_onto(base: str, head: str, cwd: str | None = None) -> Merge:
    """Merge head into base in the object store only, as the queue would."""
    proc = git(["merge-tree", "--write-tree", "--name-only", "--no-messages", base, head], cwd)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"git merge-tree {base} {head} failed: {proc.stderr.strip()}")
    tree, *files = proc.stdout.splitlines()
    if proc.returncode == 1:
        return Merge(None, tuple(f for f in files if f))
    commit = git(["commit-tree", tree, "-p", base, "-p", head, "-m", "pr:conflicts replay"], cwd)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit-tree failed: {commit.stderr.strip()}")
    return Merge(commit.stdout.strip(), ())


def queue_conflicts(base: str, first: str, second: str, cwd: str | None = None) -> tuple[str, ...]:
    """Files the second PR conflicts on once the first has landed on base."""
    landed = merge_onto(base, first, cwd)
    if landed.commit is None:
        return ()  # the first PR conflicts with base itself; reported on its own
    return merge_onto(landed.commit, second, cwd).conflicts


def default_prs() -> list[int]:
    rc, out, err = gh(
        ["pr", "list", "--author", "@me", "--state", "open", "--json", "number,isDraft"],
        GH_TIMEOUT_S,
    )
    if rc != 0:
        eprint(f"gh pr list failed:\n{err.strip()[:400]}")
        sys.exit(2)
    return sorted(pr["number"] for pr in json.loads(out) if not pr["isDraft"])


def fetch(prs: list[int]) -> None:
    refspecs = [f"+{BASE_BRANCH}:{PR_REF_PREFIX}/base"]
    refspecs += [f"+pull/{n}/head:{PR_REF_PREFIX}/{n}" for n in prs]
    proc = git(["fetch", "--quiet", "--no-tags", "origin", *refspecs])
    if proc.returncode != 0:
        eprint(f"git fetch failed:\n{proc.stderr.strip()[:400]}")
        sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prs", nargs="*", type=int, help="PR numbers (default: your open PRs)")
    args = parser.parse_args(argv)
    prs = sorted(set(args.prs)) or default_prs()
    if not prs:
        print("no open PRs to check")
        return 0
    fetch(prs)
    base = f"{PR_REF_PREFIX}/base"
    ref = {n: f"{PR_REF_PREFIX}/{n}" for n in prs}

    found = False
    for n in prs:
        files = merge_onto(base, ref[n]).conflicts
        if files:
            found = True
            print(f"#{n} conflicts with {BASE_BRANCH}: {', '.join(files)}")
    for a, b in combinations(prs, 2):
        files = queue_conflicts(base, ref[a], ref[b])
        if files:
            found = True
            print(f"#{a} + #{b} conflict: {', '.join(files)}")
            print(f"  queue #{a} first, then merge {BASE_BRANCH} into #{b} once it lands")
    if not found:
        listed = " ".join(f"#{n}" for n in prs)
        print(f"{listed}: no conflicts with {BASE_BRANCH} or each other, queue in any order")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
