"""Pin which projects' tasks nx marks affected for each kind of change.

CI opens and closes whole lanes on this answer, so a wrong nx.json or
project.json input skips tests silently. uv.lock once selected voice-agent
alone, so a Python dependency bump skipped the API suites; pnpm-lock.yaml
selected every project, so a JS bump ran all five Python slices.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from doc_shape import sequence
from lib import nx_affected
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DETECT_TASK_GATE = re.compile(r"contains\(fromJSON\(needs\.detect\.outputs\.tasks\), '([\w:-]+)'\)")

PYTHON = {"api", "shared-python", "voice-agent"}
JS = {
    "artifact-validate",
    "artifacts",
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
    "usercontent-worker",
    "wake-word",
    "web",
}

# Merged master commits: a range keeps the lockfile diff, which --files reduces to a whole-file change.
PNPM_OVERRIDES_BUMP = "97a05f7e7c"  # #1565: package.json overrides + pnpm-lock.yaml
UV_LOCK_BUMP = "d980793bca"  # #1564: pyproject.toml + uv.lock


# The code projects' own targets; the .github/jobs projects are pinned by test_workflow_nx_gates.
CODE_TARGETS = ("build", "lint", "test", "type-check")


def affected_tasks(*args: str) -> set[str]:
    return set(nx_affected.explain(list(CODE_TARGETS), list(args)))


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
    monkeypatch.setenv("PNPM_AUDIT_LEVEL", "bogus")
    results, _, passed = _run(["ci:pnpm-audit", "ci:ignore-whys"])
    assert not passed
    assert results["ci:pnpm-audit"]["status"] == "failure"
    assert "PNPM_AUDIT_LEVEL must be one of" in results["ci:pnpm-audit"]["output"]
    assert results["ci:ignore-whys"]["status"] == "success"


def test_a_task_that_rewrites_tracked_files_runs_before_the_rest() -> None:
    _, order, _ = _run(["ci:ignore-whys", "ci:cli-config-schema"])
    assert order[0] == "ci:cli-config-schema"


def test_a_build_chain_reports_through_the_plugin() -> None:
    known = nx_affected.checks()
    assert known["web:build"].chained and known["ci:seo"].chained
    assert not known["ci:ruff"].chained and known["ci:api-schema"].exclusive


def test_a_failing_nx_command_raises_with_what_nx_said() -> None:
    with pytest.raises(
        nx_affected.NxFailedError, match=r"`nx show project no-such-project` exited [1-9]"
    ) as failed:
        nx_affected._nx("show", "project", "no-such-project")
    assert "no-such-project" in str(failed.value).split("\n", 1)[1]


# ── the verified tier: a master push the merge queue already passed ─────────


def _check(
    task: str,
    job: str,
    events: tuple[str, ...] | None = None,
    branch: str | None = None,
    runner: str = "nx",
) -> nx_affected.Check:
    return nx_affected.Check(
        task=task, job=job, check=task.split(":", 1)[1], area="build",
        events=events, branch=branch, reuse=True, runner=runner,
    )  # fmt: skip


VERIFIED_CHECKS = {
    c.task: c
    for c in [
        _check("ci:ruff", "lint-python"),
        _check("web:build", "ts-build-test"),
        _check("ci:web-bundle", "web-build"),
        _check("ci:analytics-sync", "lint-mixed", events=("push",), branch="master", runner="step"),
        _check("ci:analytics-check", "lint-mixed"),
        _check("api:test", "test-python"),
        _check("web:e2e-screen", "web-e2e-screen"),
        _check("bot-harness:e2e", "bot-harness-e2e"),
        _check("ci:desktop-package-deps", "desktop-build", events=("merge_group", "push")),
    ]
}


@pytest.fixture
def verified_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nx_affected, "checks", lambda: VERIFIED_CHECKS)
    monkeypatch.setattr(nx_affected, "release_groups", lambda _selection: [])


def _published(tier: str) -> dict[str, object]:
    selection = nx_affected.Selection(tasks={task: [] for task in VERIFIED_CHECKS})
    published = nx_affected.outputs(selection, "push", "master", tier)
    return {key: json.loads(value) for key, value in published.items()}


@pytest.mark.usefixtures("verified_checks")
def test_a_verified_push_keeps_only_the_shipped_bundle_and_the_master_only_publishing() -> None:
    published = _published("verified")

    assert published["tasks"] == ["ci:analytics-sync", "ci:web-bundle", "web:build"]
    assert published["jobs"] == ["lint-mixed", "web-build"]
    assert published["job_tasks"] == {
        "lint-mixed": ["ci:analytics-sync"],
        "web-build": ["ci:web-bundle"],
    }


@pytest.mark.usefixtures("verified_checks")
def test_the_full_tier_keeps_every_affected_check() -> None:
    published = _published("full")

    assert published["tasks"] == sorted(VERIFIED_CHECKS)
    jobs = sequence(published["jobs"])
    assert {
        "test-python",
        "ts-build-test",
        "web-e2e-screen",
        "bot-harness-e2e",
        "desktop-build",
    } <= set(jobs)


def _production_deploy_gates() -> dict[str, list[str]]:
    """Map each ci.yml production job to the affected tasks its `if:` waits on."""
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    return {
        name: DETECT_TASK_GATE.findall(str(job.get("if", "")))
        for name, job in jobs.items()
        if job.get("environment") == "production"
    }


@pytest.mark.usefixtures("verified_checks")
def test_a_verified_push_keeps_every_task_a_production_deploy_waits_on() -> None:
    """Regression: a verified push dropped usercontent-worker:build, so the Worker never deployed."""
    gates = _production_deploy_gates()
    assert gates.get("deploy-usercontent-worker"), (
        "the Worker deploy no longer gates on detect's tasks"
    )
    for job, tasks in gates.items():
        for task in tasks:
            selection = nx_affected.Selection(tasks={task: []})
            published = json.loads(
                nx_affected.outputs(selection, "push", "master", "verified")["tasks"]
            )
            assert published == [task], f"{job} waits on {task}, which a verified push drops"
