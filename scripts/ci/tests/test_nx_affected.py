"""Pin which projects' tasks nx marks affected for each kind of change.

CI opens and closes whole lanes on this answer, so a wrong nx.json or
project.json input skips tests silently. uv.lock once selected voice-agent
alone, so a Python dependency bump skipped the API suites; pnpm-lock.yaml
selected every project, so a JS bump ran all five Python slices.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

PYTHON = {"api", "shared-python", "voice-agent"}
JS = {
    "bot-discord",
    "bot-harness",
    "bot-imessage",
    "bot-slack",
    "bot-telegram",
    "bot-whatsapp",
    "bots-e2e",
    "cli",
    "desktop",
    "mobile",
    "shared-typescript",
    "wake-word",
    "web",
}

# Merged master commits: a range keeps the lockfile diff, which --files reduces to a whole-file change.
PNPM_OVERRIDES_BUMP = "97a05f7e7c"  # #1565: package.json overrides + pnpm-lock.yaml
UV_LOCK_BUMP = "d980793bca"  # #1564: pyproject.toml + uv.lock


# The code projects' own targets; the .github/jobs projects are pinned by test_workflow_nx_gates.
CODE_TARGETS = ("build", "lint", "test", "type-check")


def affected_tasks(*args: str) -> set[str]:
    out = subprocess.run(
        ["pnpm", "exec", "nx", "affected", "-t", *CODE_TARGETS, "--explain=stdout", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "NX_NO_CLOUD": "true", "NX_DAEMON": "false"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(json.loads(out[out.index("{") :])["affected"])


def affected(*args: str) -> set[str]:
    return {task.split(":", 1)[0] for task in affected_tasks(*args)}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", set()),
        ("package.json", JS),
        ("uv.lock", PYTHON),
        ("pyproject.toml", PYTHON),
        ("libs/pyproject.toml", PYTHON),
        ("libs/shared/py/__init__.py", PYTHON),
        # shared-python's mypy runs in the API's environment.
        ("apps/api/pyproject.toml", {"api", "shared-python"}),
        ("apps/api/app/main.py", {"api"}),
        ("apps/voice-agent/pyproject.toml", {"voice-agent"}),
        ("docs/introduction.mdx", set()),
    ],
)
def test_changed_file_selects_its_projects(path: str, expected: set[str]) -> None:
    assert affected(f"--files={path}") == expected


@pytest.mark.parametrize(
    ("commit", "expected"),
    [(PNPM_OVERRIDES_BUMP, JS), (UV_LOCK_BUMP, PYTHON)],
)
def test_dependency_bump_selects_one_language(commit: str, expected: set[str]) -> None:
    assert affected(f"--base={commit}^", f"--head={commit}") == expected


@pytest.mark.parametrize(
    ("path", "task"),
    [
        ("libs/shared/py/__init__.py", "api:test"),
        ("libs/pyproject.toml", "api:test"),
        ("uv.lock", "api:test"),
        ("libs/shared/ts/src/index.ts", "web:test"),
        ("libs/shared/ts/src/index.ts", "web:type-check"),
    ],
)
def test_dependency_change_reaches_dependent_task(path: str, task: str) -> None:
    assert task in affected_tasks(f"--files={path}")
