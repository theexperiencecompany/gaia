"""A prek hook that regenerates a check's output watches exactly the files that check's nx task reads.

prek needs a literal `files:` regex, so the hook carries a copy of what nx
knows. A file the hook misses commits a stale artifact that CI then fails; a
file only the hook sees regenerates for nothing.
"""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
# The hooks that regenerate a check's artifact, and the task that checks it.
HOOK_TASKS = {
    "api-types": "lint-mixed:api-schema",
    "analytics-types": "lint-mixed:analytics-catalog",
}
# Every check reads the CI harness (nx.json's ciHarness); a hook has no reason to.
HARNESS_PATTERNS = {
    p.removeprefix("{workspaceRoot}/")
    for p in json.loads((REPO_ROOT / "nx.json").read_text())["namedInputs"]["ciHarness"]
}
# nx makes these an input of every task; no lane regex names them.
NX_IMPLICIT_INPUTS = {".gitignore", ".nxignore", "nx.json", "tsconfig.base.json", "tsconfig.json"}


def _git_files(*args: str) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def _tracked_files() -> list[str]:
    seen_by_nx = _git_files() - _git_files("-c", "-i", "--exclude-from=.nxignore")
    return sorted(f for f in seen_by_nx if (REPO_ROOT / f).is_file())


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    return _tracked_files()


@pytest.fixture(scope="module")
def nx_files(tracked: list[str]) -> dict[str, set[str]]:
    targets = sorted({task.split(":", 1)[1] for task in HOOK_TASKS.values()})
    out = subprocess.run(
        [
            "pnpm",
            "exec",
            "nx",
            "affected",
            "-t",
            *targets,
            "--files",
            *tracked,
            "--explain=stdout",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "NX_NO_CLOUD": "true", "NX_DAEMON": "false"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    affected = json.loads(out[out.index("{") :])["affected"]
    files: dict[str, set[str]] = defaultdict(set)
    for task, reasons in affected.items():
        files[task] |= {
            r["file"]
            for r in reasons
            if r["kind"] == "input-file" and r.get("pattern") not in HARNESS_PATTERNS
        } - NX_IMPLICIT_INPUTS
    return files


def _hook_files(hook_id: str) -> str:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    (hook,) = [h for repo in config["repos"] for h in repo.get("hooks", []) if h["id"] == hook_id]
    return str(hook["files"])


@pytest.mark.parametrize(("hook_id", "task"), sorted(HOOK_TASKS.items()))
def test_hook_watches_what_the_check_reads(
    hook_id: str, task: str, tracked: list[str], nx_files: dict[str, set[str]]
) -> None:
    files = re.compile(_hook_files(hook_id))
    by_hook = {f for f in tracked if files.search(f)} - NX_IMPLICIT_INPUTS
    assert sorted(by_hook - nx_files[task]) == [], f"only the {hook_id} hook selects these"
    assert sorted(nx_files[task] - by_hook) == [], (
        f"only {task}'s inputs select these; add them to the hook"
    )
