"""Every heavy nx step in ci.yml queues through the host CPU governor.

`lib/cpu-slots.sh` only governs the lanes that ask it to. A lane that sizes its
own parallelism from `runner.py parallel` and then runs nx directly takes those
cores whether or not the box has them, and the cost lands on whichever
neighbour has a deadline: `test-typescript` was unenrolled, and a jsdom render
that takes 137 ms idle blew vitest's 5 s timeout on the loaded box, failed the
lane, and passed unchanged on the next run.

Being unenrolled is invisible — the lane is green whenever the box happens to
be quiet — so the only way to notice is a test that reads the workflow.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from doc_shape import mapping
from lib import nx_affected
import pytest
import runner
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return mapping(yaml.safe_load(CI_YML.read_text()))


def test_no_step_runs_nx_across_the_workspace_outside_the_governor(
    workflow: dict[str, Any],
) -> None:
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            if "nx run-many" in run:
                assert "runner.py with-slots" in run, (
                    f"{name}: {step.get('name')} skips the governor"
                )


def test_run_job_holds_as_many_tokens_as_it_asks_nx_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Hold as many tokens as nx spawns workers, or the box is oversubscribed on the quiet."""
    asked: dict[str, Any] = {}

    def fake_run(tasks: list[str], parallel: int, wrap: Any, on_done: Any) -> bool:
        asked.update(tasks=tasks, parallel=parallel, many=wrap(parallel), one=wrap(1))
        return True

    check = nx_affected.Check("ci:biome", "lint-node", "biome", "node", None, None, True, "nx")
    monkeypatch.setattr(nx_affected, "checks", lambda: {check.task: check})
    monkeypatch.setattr(nx_affected, "run", fake_run)
    monkeypatch.setattr(runner, "measure_parallelism", lambda: _parallelism(nx=6))
    monkeypatch.setenv("JOB_TASKS", json.dumps({"lint-node": ["ci:biome"]}))
    monkeypatch.setenv("RESULTS_FILE", str(tmp_path / "results.json"))
    monkeypatch.delenv("REUSED", raising=False)

    assert runner.cmd_run_job(["lint-node"]) == 0
    assert asked["tasks"] == ["ci:biome"] and asked["parallel"] == 6
    assert "with-slots" in asked["many"] and asked["many"][-1] == "6"
    assert asked["one"][-1] == "1", "a single-task nx run holds one token"


def _parallelism(nx: int) -> Any:
    return runner.Parallelism(
        nproc=8, mem_gb=16, mem_avail_gb=8, nx=nx, pytest_n=4, pytest_capped=False, docker=2
    )


def test_run_job_posts_each_check_the_moment_its_tasks_finish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: every status waited for the job's slowest check, so a quick red showed late."""
    posts: list[str] = []
    seen_when_deps_finished: list[str] = []
    checks = [
        nx_affected.Check("ci:biome", "lint-node", "biome", "node", None, None, True, "nx"),
        nx_affected.Check(
            "web:type-check", "lint-node", "type-check", "node", None, None, True, "nx"
        ),
        nx_affected.Check(
            "cli:type-check", "lint-node", "type-check", "node", None, None, True, "nx"
        ),
    ]

    def fake_run(tasks: list[str], parallel: int, wrap: Any, on_done: Any) -> bool:
        on_done("ci:biome", {"status": "failure", "code": 1, "output": "a.ts:1:1 lint"})
        on_done("web:type-check", {"status": "success", "code": 0, "output": ""})
        seen_when_deps_finished.extend(posts)
        on_done("cli:type-check", {"status": "success", "code": 0, "output": ""})
        return False

    def fake_post(argv: list[str], **_: Any) -> None:
        posts.append(argv[argv.index("--check") + 1])

    monkeypatch.setattr(nx_affected, "checks", lambda: {c.task: c for c in checks})
    monkeypatch.setattr(nx_affected, "run", fake_run)
    monkeypatch.setattr(subprocess, "run", fake_post)
    monkeypatch.setattr(runner, "measure_parallelism", lambda: _parallelism(nx=2))
    monkeypatch.setenv("JOB_TASKS", json.dumps({"lint-node": [c.task for c in checks]}))
    monkeypatch.setenv("RESULTS_FILE", str(tmp_path / "results.json"))
    monkeypatch.setenv("NO_POST", "--no-post")

    assert runner.cmd_run_job(["lint-node"]) == 1
    # biome posted before type-check's second task finished; type-check only once both had.
    assert seen_when_deps_finished == ["biome"]
    assert posts == ["biome", "type-check"]
