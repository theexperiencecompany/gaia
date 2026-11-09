"""Every ci.yml gate names a task nx can select, and every check is gated by one.

detect writes the affected tasks and, from each target's metadata.ci.job, the
jobs with a check to run (changes.sh affected); a job runs when it is named and
a step when its own task is in the job's list. A gate naming a task detect never asks about is a check that silently
never runs; a check with no gate runs on every change, README included.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from doc_shape import mapping
from lib import nx_affected
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
TASK_GATE = re.compile(r"outputs\.tasks\), '([^']+)'\)")
JOB_GATE = re.compile(r"outputs\.jobs\), '([^']+)'\)")
JOB_TASK_GATE = re.compile(r"outputs\.job_tasks\)\['([\w-]+)'\], '([^']+)'\)")


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
CHECKS = nx_affected.checks()
CHECK_JOBS = {check.job for check in CHECKS.values()}


def _gating_jobs() -> dict[str, Any]:
    """Every job of every workflow that gates on detect's answer, by job id."""
    found: dict[str, Any] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        if "outputs.tasks" in text or "outputs.jobs" in text:
            found |= mapping(yaml.safe_load(text))["jobs"]
    return found


@pytest.fixture(scope="module")
def jobs() -> dict[str, Any]:
    return _gating_jobs()


def test_every_gated_task_is_one_detect_asks_nx_about(jobs: dict[str, Any]) -> None:
    named = {t for job in jobs.values() for t in TASK_GATE.findall(json.dumps(job))}
    named |= {t for job in jobs.values() for _, t in JOB_TASK_GATE.findall(json.dumps(job))}
    unknown = sorted(
        t
        for t in named
        if (t not in CHECKS and not t.endswith(f":{nx_affected.IMAGE_TARGET}"))
        or t.split(":", 1)[1] not in PROJECTS.get(t.split(":", 1)[0], set())
    )
    assert unknown == [], "gates on tasks nx_affected never selects or that no project defines"


def test_a_step_reads_only_its_own_jobs_tasks(jobs: dict[str, Any]) -> None:
    for name, job in jobs.items():
        for owner, task in JOB_TASK_GATE.findall(json.dumps(job)):
            assert owner == name, f"{name} gates on {owner}'s tasks"
            assert CHECKS[task].job == name, (
                f"{name} gates on {task}, a check of {CHECKS[task].job}"
            )


def test_every_gated_job_is_one_a_check_names(jobs: dict[str, Any]) -> None:
    named = {j for job in jobs.values() for j in JOB_GATE.findall(json.dumps(job))}
    assert named <= CHECK_JOBS


@pytest.mark.parametrize(
    "name", sorted(CHECK_JOBS - {"selfhost-smoke", "test-python", "test-mutation"})
)
def test_a_job_starts_when_detect_names_it(name: str, jobs: dict[str, Any]) -> None:
    assert f"contains(fromJSON(needs.detect.outputs.jobs), '{name}')" in str(jobs[name]["if"])


def test_no_workflow_step_repeats_a_checks_command(jobs: dict[str, Any]) -> None:
    """One command per check: a step that spells a target's command out is a copy that drifts."""
    commands = {
        str(spec["options"]["command"]).strip()
        for spec in (t for t in _run_commands_targets().values())
    }
    copies = [
        (name, s.get("name"))
        for name, job in jobs.items()
        for s in job.get("steps", [])
        if str(s.get("run", "")).strip() in commands
    ]
    assert copies == []


def _run_commands_targets() -> dict[str, dict[str, Any]]:
    manifests = subprocess.run(
        ["git", "ls-files", "*project.json"],
        cwd=nx_affected.REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    out: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        project = json.loads((nx_affected.REPO_ROOT / manifest).read_text())
        for target, spec in project.get("targets", {}).items():
            if spec.get("executor") == "nx:run-commands" and "command" in spec.get("options", {}):
                out[f"{project['name']}:{target}"] = spec
    return out


@pytest.mark.parametrize(
    ("path", "task"),
    [
        # #1492: a scripts/-only change once skipped every Python lint.
        ("scripts/dev/gaia_verify.py", "ci:plr-complexity"),
        ("scripts/dev/gaia_verify.py", "ci:ruff"),
        ("libs/shared/py/__init__.py", "api:test"),
        ("tools/gaia-connect/main.go", "gaia-connect:check"),
        ("config/pint.hcl", "alert-rules:check"),
        (".github/workflows/ci.yml", "ci:harness-tests"),
        # The per-Dockerfile ignore file decides what enters the build context.
        ("apps/api/Dockerfile.dockerignore", "ci:api-image"),
        (".dockerignore", "ci:api-image"),
        ("config/squirrel.toml", "ci:seo"),
        ("libs/shared/ts/src/index.ts", "ci:seo"),
        ("packages/cli/src/index.ts", "ci:selfhost-e2e"),
        ("packages/cli/selfhost/docker-compose.selfhost.yml", "ci:selfhost-e2e"),
        # The web bundle syncs the wake-word runtime and bundles shared-typescript.
        ("libs/wake-word/src/web/runtime.ts", "web:build"),
        ("libs/shared/ts/src/index.ts", "web:build"),
        ("scripts/ci/smoke-worker.sh", "ci:web-bundle"),
        ("apps/desktop/src/main/index.ts", "desktop:build"),
        ("apps/web/src/app/page.tsx", "desktop:build"),
        (".github/workflows/desktop-pr-build.yml", "ci:desktop-package"),
        # The images build.yml publishes: the Python lockfile and the bots' shared Dockerfile.
        ("uv.lock", "api:docker:build"),
        ("uv.lock", "voice-agent:docker:build"),
        ("apps/bots/Dockerfile", "bot-discord:docker:build"),
        ("libs/shared/ts/src/index.ts", "bot-slack:docker:build"),
        # A deleted file is a change: a per-file-ignores entry for it goes stale.
        ("apps/api/app/gone_module.py", "ci:ignore-staleness"),
    ],
)
def test_detect_selects(path: str, task: str) -> None:
    assert task in nx_affected.select([f"--files={path}"]).tasks


@pytest.mark.parametrize(
    ("path", "task"),
    [
        # Code alone rebuilds the last COPY layer and proves nothing the tests do not.
        ("apps/api/app/main.py", "ci:api-image"),
        ("apps/api/app/main.py", "ci:seo"),
        ("pnpm-lock.yaml", "api:test"),
        ("apps/api/app/main.py", "ci:selfhost-e2e"),
        ("apps/api/app/main.py", "web:build"),
        ("scripts/ci/deploy.sh", "ci:desktop-package"),
        ("apps/api/CLAUDE.md", "api:docker:build"),
        ("pnpm-lock.yaml", "api:docker:build"),
    ],
)
def test_detect_leaves_out(path: str, task: str) -> None:
    assert task not in nx_affected.select([f"--files={path}"]).tasks


@pytest.mark.parametrize("path", ["README.md", "docs/introduction.mdx", "apps/api/CLAUDE.md"])
def test_detect_selects_only_repo_wide_checks_for_prose(path: str) -> None:
    # Prose is where the bot handle copies live, and a secret can land in any
    # file, so both scans read everything; nothing else wakes up for a doc edit.
    assert set(nx_affected.select([f"--files={path}"]).tasks) == {
        "ci:gitleaks",
        "ci:bot-handles",
    }


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
        ("pyproject.toml", "ci:ruff", nx_affected.FULL_SCAN),
        ("biome.json", "ci:biome", nx_affected.FULL_SCAN),
        # tsconfig*.json is a config glob, not a source one: every file is type-checked again.
        ("apps/web/tsconfig.json", "web:type-check", nx_affected.FULL_SCAN),
        ("apps/api/app/main.py", "ci:ruff", ["apps/api/app/main.py"]),
        # interrogate scans the three packages; a lint tool outside them failed its 80% bar.
        ("tools/lints/_common.py", "ci:interrogate", None),
        ("apps/api/app/main.py", "ci:bandit", ["apps/api/app/main.py"]),
        ("apps/api/tests/conftest.py", "ci:bandit", None),
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
    selection = nx_affected.Selection(tasks={"ci:ruff": reasons})
    assert nx_affected.task_files(selection) == {"ci:ruff": nx_affected.FULL_SCAN}


def test_a_check_gets_every_file_however_large_the_map(tmp_path: Path) -> None:
    """Regression: a 233-file PR's map (139,600 bytes) rode one env var, over Linux's 128 KiB cap."""
    files = [f"apps/api/app/services/module_{n:04}.py" for n in range(250)]
    task_map = {f"ci:check-{i}": files for i in range(15)}
    path = tmp_path / "task-files.json"
    path.write_text(json.dumps(task_map))
    assert len(path.read_text()) > 128 * 1024
    out = subprocess.run(
        [sys.executable, str(nx_affected.REPO_ROOT / "scripts/ci/lib/nx_affected.py"),
         "--files-for", "ci:check-7", "--base", "HEAD"],
        env={**os.environ, nx_affected.TASK_FILES_ENV: str(path)},
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert out.split() == files


def test_no_job_carries_task_files_in_its_environment() -> None:
    text = (WORKFLOWS / "ci.yml").read_text()
    assert "outputs.task_files" not in text
    jobs = mapping(yaml.safe_load(text))["jobs"]
    for name, job in jobs.items():
        steps = job.get("steps", [])
        runs = [i for i, st in enumerate(steps) if "runner.py run-job" in str(st.get("run", ""))]
        if runs:
            fetch = [
                i for i, st in enumerate(steps) if st.get("uses") == "./.github/actions/task-files"
            ]
            assert fetch and fetch[0] < runs[0], (
                f"{name} runs its checks without detect's task files"
            )


def test_a_check_lists_its_config_before_its_source_globs() -> None:
    """Nx names the first input a file matches; biome.json read as a source file scoped biome to itself."""
    for path in [REPO_ROOT / "tools" / "ci" / "project.json"]:
        for target, spec in json.loads(path.read_text())["targets"].items():
            kinds = [
                "src" if nx_affected.SOURCE_GLOB.search(i) else "cfg"
                for i in spec["inputs"]
                if isinstance(i, str) and not i.startswith("!")
            ]
            assert kinds == sorted(kinds), (
                f"{path.parent.name}:{target} lists a config input after a source glob"
            )
