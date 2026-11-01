"""Every ci.yml gate names a task nx can select, and every check is gated by one.

detect writes the affected tasks (changes.sh affected); a job runs when its
project under .github/jobs has one and a step when its own task is in the
list. A gate naming a task detect never asks about is a check that silently
never runs; a check with no gate runs on every change, README included.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from doc_shape import mapping
from lib import nx_affected
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LANES = json.loads((REPO_ROOT / "scripts" / "dev" / "verify-lanes.json").read_text())["lanes"]
TASK_GATE = re.compile(r"outputs\.tasks\), '([^']+)'\)")
PROJECT_GATE = re.compile(r"outputs\.projects\), '([^']+)'\)")
# Run on every change on purpose: a secret can land in any file.
ALWAYS = {("repo-policy", "gitleaks")}


def _projects() -> dict[str, set[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        graph_file = Path(tmp) / "graph.json"
        subprocess.run(
            ["pnpm", "exec", "nx", "graph", f"--file={graph_file}"],
            cwd=REPO_ROOT,
            env={**os.environ, "NX_NO_CLOUD": "true", "NX_DAEMON": "false"},
            capture_output=True,
            check=True,
        )
        nodes = json.loads(graph_file.read_text())["graph"]["nodes"]
    return {name: set(node["data"].get("targets", {})) for name, node in nodes.items()}


PROJECTS = _projects()
JOB_PROJECTS = {p.parent.name for p in nx_affected.JOBS_DIR.glob("*/project.json")}
REQUESTED = set(nx_affected.job_targets()) | set(nx_affected.CODE_TARGETS)


def _gating_jobs() -> dict[str, Any]:
    """Every job of every workflow that gates on detect's tasks, by job id."""
    found: dict[str, Any] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        if "outputs.tasks" in text:
            found |= mapping(yaml.safe_load(text))["jobs"]
    return found


@pytest.fixture(scope="module")
def jobs() -> dict[str, Any]:
    return _gating_jobs()


def _gated_tasks(job: dict[str, Any]) -> list[tuple[str | None, str]]:
    return [
        (step.get("id"), task)
        for step in job.get("steps", [])
        for task in TASK_GATE.findall(str(step.get("if", "")))
    ]


def test_every_gated_task_is_one_detect_asks_nx_about(jobs: dict[str, Any]) -> None:
    named = {t for job in jobs.values() for t in TASK_GATE.findall(json.dumps(job))}
    unknown = sorted(
        t
        for t in named
        if t.split(":", 1)[1] not in REQUESTED
        or t.split(":", 1)[1] not in PROJECTS.get(t.split(":", 1)[0], set())
    )
    assert unknown == [], "gates on tasks nx_affected never selects or that no project defines"


def test_every_gated_project_is_a_job_project(jobs: dict[str, Any]) -> None:
    named = {p for job in jobs.values() for p in PROJECT_GATE.findall(str(job.get("if", "")))}
    assert named <= JOB_PROJECTS


def test_a_job_project_is_named_after_its_job(jobs: dict[str, Any]) -> None:
    assert set(jobs) >= JOB_PROJECTS


@pytest.mark.parametrize("name", sorted(JOB_PROJECTS))
def test_every_job_target_gates_that_job(name: str, jobs: dict[str, Any]) -> None:
    gated = set(TASK_GATE.findall(json.dumps(jobs[name])))
    # A job's own checks may be decided by the job that asks nx (detect, changes).
    gated |= {t for job in ("detect", "changes") for t in TASK_GATE.findall(json.dumps(jobs[job]))}
    assert sorted(f"{name}:{t}" for t in PROJECTS[name] if f"{name}:{t}" not in gated) == []


@pytest.mark.parametrize("name", sorted(JOB_PROJECTS - {"test-mutation", "selfhost-smoke"}))
def test_a_job_starts_whenever_one_of_its_steps_would(name: str, jobs: dict[str, Any]) -> None:
    job_if = str(jobs[name].get("if", ""))
    for _, task in _gated_tasks(jobs[name]):
        project = task.split(":", 1)[0]
        assert project == name or f"'{task}'" in job_if, (
            f"{task} can never run: {name} does not start for it"
        )
    starts_for_own_work = f"'{name}'" in job_if or f"'{name}:" in job_if
    assert starts_for_own_work or "tier != ''" in job_if


def test_every_check_step_is_gated(jobs: dict[str, Any]) -> None:
    ungated = [
        (name, step["id"])
        for name, job in jobs.items()
        for step in job.get("steps", [])
        if step.get("continue-on-error")
        and step.get("id")
        and not re.search(r"outputs\.(tasks|typescript_projects)|steps\.", str(step.get("if", "")))
        and (name, step["id"]) not in ALWAYS
    ]
    assert ungated == []


@pytest.mark.parametrize(
    "lane",
    [lane for lane in LANES if "nx" in lane and "ci_check" in lane],
    ids=lambda lane: lane["name"],
)
def test_a_lane_check_is_gated_on_its_lane_task(lane: dict[str, str], jobs: dict[str, Any]) -> None:
    (job,) = [
        j for j in jobs.values() if any(s.get("id") == lane["ci_check"] for s in j.get("steps", []))
    ]
    by_id = {s["id"]: str(s.get("if", "")) for s in job["steps"] if s.get("id")}
    gate = by_id[lane["ci_check"]]
    # A background check reports in one step and is started, and gated, by the one it names.
    gate += "".join(
        by_id.get(started, "") for started in re.findall(r"steps\.([a-z-]+)\.outcome", gate)
    )
    assert f"'{lane['nx']}'" in gate


@pytest.mark.parametrize(
    ("path", "task"),
    [
        # #1492: a scripts/-only change once skipped every Python lint.
        ("scripts/dev/gaia_verify.py", "lint-python:plr-complexity"),
        ("scripts/dev/gaia_verify.py", "lint-python:ruff"),
        ("libs/shared/py/__init__.py", "api:test"),
        ("tools/gaia-connect/main.go", "gaia-connect:check"),
        ("config/pint.hcl", "alert-rules:check"),
        (".github/workflows/ci.yml", "lint-mixed:harness-tests"),
        # The per-Dockerfile ignore file decides what enters the build context.
        ("apps/api/Dockerfile.dockerignore", "docker-image:api-image"),
        (".dockerignore", "docker-image:api-image"),
        ("config/squirrel.toml", "ts-build-test:seo"),
        ("libs/shared/ts/src/index.ts", "ts-build-test:seo"),
        ("packages/cli/src/index.ts", "selfhost-smoke:e2e"),
        ("infra/docker/docker-compose.selfhost.yml", "selfhost-smoke:e2e"),
        # The web bundle syncs the wake-word runtime and bundles shared-typescript.
        ("libs/wake-word/src/web/runtime.ts", "web:build"),
        ("libs/shared/ts/src/index.ts", "web:build"),
        ("scripts/ci/smoke-worker.sh", "web-build:bundle"),
        ("apps/desktop/src/main/index.ts", "desktop:build"),
        ("apps/web/src/app/page.tsx", "desktop:build"),
        (".github/workflows/desktop-pr-build.yml", "desktop-build:package"),
        # The images build.yml publishes: the Python lockfile and the bots' shared Dockerfile.
        ("uv.lock", "api:docker:build"),
        ("uv.lock", "voice-agent:docker:build"),
        ("apps/bots/Dockerfile", "bot-discord:docker:build"),
        ("libs/shared/ts/src/index.ts", "bot-slack:docker:build"),
        # A deleted file is a change: a per-file-ignores entry for it goes stale.
        ("apps/api/app/gone_module.py", "lint-python:ignore-staleness"),
    ],
)
def test_detect_selects(path: str, task: str) -> None:
    assert task in nx_affected.select([f"--files={path}"]).tasks


@pytest.mark.parametrize(
    ("path", "task"),
    [
        # Code alone rebuilds the last COPY layer and proves nothing the tests do not.
        ("apps/api/app/main.py", "docker-image:api-image"),
        ("apps/api/app/main.py", "ts-build-test:seo"),
        ("pnpm-lock.yaml", "api:test"),
        ("apps/api/app/main.py", "selfhost-smoke:e2e"),
        ("apps/api/app/main.py", "web:build"),
        ("scripts/ci/deploy.sh", "desktop-build:package"),
        ("apps/api/CLAUDE.md", "api:docker:build"),
        ("pnpm-lock.yaml", "api:docker:build"),
    ],
)
def test_detect_leaves_out(path: str, task: str) -> None:
    assert task not in nx_affected.select([f"--files={path}"]).tasks


@pytest.mark.parametrize("path", ["README.md", "docs/introduction.mdx", "apps/api/CLAUDE.md"])
def test_detect_selects_nothing_for_prose(path: str) -> None:
    assert nx_affected.select([f"--files={path}"]).tasks == {}


@pytest.mark.parametrize(
    ("path", "groups"),
    [("uv.lock", ["apps"]), ("apps/bots/Dockerfile", ["bots"]), ("apps/api/CLAUDE.md", [])],
)
def test_release_groups_name_the_images_to_publish(path: str, groups: list[str]) -> None:
    assert nx_affected.release_groups(nx_affected.select([f"--files={path}"])) == groups


@pytest.mark.parametrize(
    ("path", "task", "files"),
    [
        # ruff's config changed: every file is re-linted, not the zero .py files the diff holds.
        ("pyproject.toml", "lint-python:ruff", nx_affected.FULL_SCAN),
        ("biome.json", "lint-node:biome", nx_affected.FULL_SCAN),
        # tsconfig*.json is a config glob, not a source one: every file is type-checked again.
        ("apps/web/tsconfig.json", "lint-node:ts-type-check", nx_affected.FULL_SCAN),
        ("apps/api/app/main.py", "lint-python:ruff", ["apps/api/app/main.py"]),
        # interrogate scans the three packages; a lint tool outside them failed its 80% bar.
        ("tools/lints/_common.py", "lint-python:interrogate", None),
        ("apps/api/app/main.py", "lint-python:bandit", ["apps/api/app/main.py"]),
        ("apps/api/tests/conftest.py", "lint-python:bandit", None),
    ],
)
def test_a_check_is_handed_the_changed_files_it_reads(
    path: str, task: str, files: str | list[str] | None
) -> None:
    assert nx_affected.task_files(nx_affected.select([f"--files={path}"])).get(task) == files


def test_a_list_too_long_to_carry_is_a_full_scan() -> None:
    reasons = [
        {"kind": "input-file", "file": f"f{n}.py", "pattern": "**/*.py"}
        for n in range(nx_affected.SCOPED_FILES_MAX + 1)
    ]
    selection = nx_affected.Selection(tasks={"lint-python:ruff": reasons})
    assert nx_affected.task_files(selection) == {"lint-python:ruff": nx_affected.FULL_SCAN}


def test_a_check_lists_its_config_before_its_source_globs() -> None:
    """Nx names the first input a file matches; biome.json read as a source file scoped biome to itself."""
    for path in nx_affected.JOBS_DIR.glob("*/project.json"):
        for target, spec in json.loads(path.read_text())["targets"].items():
            kinds = [
                "src" if nx_affected.SOURCE_GLOB.search(i) else "cfg"
                for i in spec["inputs"]
                if isinstance(i, str) and not i.startswith("!")
            ]
            assert kinds == sorted(kinds), (
                f"{path.parent.name}:{target} lists a config input after a source glob"
            )


def _runnable_targets() -> dict[str, dict[str, str]]:
    """Every nx:run-commands target, its cwd resolved to the repo-relative path a step names."""
    manifests = subprocess.run(
        ["git", "ls-files", "*project.json"],
        cwd=nx_affected.REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    out = {}
    for manifest in manifests:
        project = json.loads((nx_affected.REPO_ROOT / manifest).read_text())
        root = str(Path(manifest).parent)
        for target, spec in project.get("targets", {}).items():
            if spec.get("executor") == "nx:run-commands" and "command" in spec.get("options", {}):
                options = dict(spec["options"])
                if "cwd" in options:
                    options["cwd"] = options["cwd"].replace("{projectRoot}", root)
                out[f"{project['name']}:{target}"] = options
    return out


def _gated_steps(jobs: dict[str, Any], task: str) -> list[dict[str, Any]]:
    return [
        s for job in jobs.values() for s in job.get("steps", [])
        if f"'{task}'" in str(s.get("if", "")) and "run" in s
    ]  # fmt: skip


def _ci_run_tasks() -> list[str]:
    gating = _gating_jobs()
    return sorted(t for t in _runnable_targets() if _gated_steps(gating, t))


@pytest.mark.parametrize("task", _ci_run_tasks())
def test_the_ci_step_runs_its_tasks_command(task: str, jobs: dict[str, Any]) -> None:
    """One command per check: CI's step and `nx run` (what mise ci:local runs) must be the same line."""
    options = _runnable_targets()[task]
    steps = _gated_steps(jobs, task)
    # A background check's step spawns its CHECK; the command is that, not the spawn.
    ran = [
        (
            str((s.get("env") or {}).get("CHECK", "")).strip()
            if "runner.py spawn" in s["run"]
            else s["run"].strip(),
            s.get("working-directory"),
        )
        for s in steps
    ]
    # Other steps on the same gate only prepare it (install pint, heal a venv).
    assert ran.count((options["command"], options.get("cwd"))) == 1, ran


def test_a_lane_with_a_runnable_task_has_no_command_of_its_own() -> None:
    runnable = _runnable_targets()
    doubled = [lane["name"] for lane in LANES if lane.get("nx") in runnable and "command" in lane]
    assert doubled == [], "verify-lanes.json repeats a command its nx task already holds"
