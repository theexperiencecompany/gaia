"""Every lane's scope regex selects exactly the files its Nx task's inputs do.

CI runs a check when nx says its task is affected, while verdict.py
reuse-plan and gaia_verify still read the lane's regex. A file one side sees
and the other misses either runs a check nothing changed or reuses a pass a
change invalidated.
"""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LANES = json.loads((REPO_ROOT / "scripts" / "dev" / "verify-lanes.json").read_text())["lanes"]
NX_LANES = [lane for lane in LANES if "nx" in lane]
# Every check reads the CI harness (nx.json's ciHarness); reuse-plan's
# GLOBAL_INVALIDATORS already covers it, so no lane regex names it.
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
    targets = sorted({lane["nx"].split(":", 1)[1] for lane in NX_LANES})
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


@pytest.mark.parametrize("lane", NX_LANES, ids=[lane["name"] for lane in NX_LANES])
def test_scope_matches_nx_inputs(
    lane: dict[str, str], tracked: list[str], nx_files: dict[str, set[str]]
) -> None:
    scope = re.compile(lane["scope"])
    by_regex = {f for f in tracked if scope.search(f)} - NX_IMPLICIT_INPUTS
    by_nx = nx_files[lane["nx"]]
    assert sorted(by_regex - by_nx) == [], f"only the scope regex selects these for {lane['nx']}"
    assert sorted(by_nx - by_regex) == [], f"only the {lane['nx']} inputs select these"
