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

from lib import nx_affected
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


def test_exact_runs_groups_targets_only_when_they_run_on_the_same_projects() -> None:
    tasks = ["api:lint", "api:type-check", "web:lint", "web:type-check", "api:test", "ci:biome"]

    runs = nx_affected.exact_runs(tasks)

    # run-many runs every target on every project it names, so web:test must never appear.
    assert runs == [
        (["api"], ["test"]),
        (["api", "web"], ["lint", "type-check"]),
        (["ci"], ["biome"]),
    ]
    product = [f"{p}:{t}" for projects, targets in runs for p in projects for t in targets]
    assert sorted(product) == sorted(tasks)


def _run(tasks: list[str]) -> tuple[dict[str, nx_affected.TaskResult], list[str], bool]:
    results: dict[str, nx_affected.TaskResult] = {}
    order: list[str] = []

    def on_done(task: str, result: nx_affected.TaskResult) -> None:
        results[task] = result
        order.append(task)

    passed = nx_affected.run(tasks, 2, lambda _cores: [], on_done)
    return results, order, passed


def test_run_hands_each_task_its_own_result_and_output() -> None:
    results, _, passed = _run(["ci:ignore-whys"])
    assert passed
    assert results["ci:ignore-whys"]["status"] == "success"
    # Unprefixed: a `ci: ` prefix on every line hides each file:line from the verdict.
    assert any(
        line.startswith("ignore-whys: OK")
        for line in results["ci:ignore-whys"]["output"].splitlines()
    )


def test_run_reports_a_failed_task_and_still_runs_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUDIT_SCOPE", "bogus")
    results, _, passed = _run(["ci:pnpm-audit", "ci:ignore-whys"])
    assert not passed
    assert results["ci:pnpm-audit"]["status"] == "failure"
    assert "AUDIT_SCOPE must be all or introduced" in results["ci:pnpm-audit"]["output"]
    assert results["ci:ignore-whys"]["status"] == "success"


def test_a_task_that_rewrites_tracked_files_runs_before_the_rest() -> None:
    _, order, _ = _run(["ci:ignore-whys", "ci:cli-config-schema"])
    assert order[0] == "ci:cli-config-schema"


def test_a_build_chain_reports_through_the_plugin() -> None:
    known = nx_affected.checks()
    assert known["web:build"].chained and known["ci:seo"].chained
    assert not known["ci:ruff"].chained and known["ci:api-schema"].exclusive
