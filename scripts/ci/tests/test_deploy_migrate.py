"""deploy.sh migrate: the release step runs first; the conversation catch-up stops writers only when it must.

``docker`` is a fake on PATH that plays a small Swarm: the backend's task template,
each writer's replica count and running tasks, and one task per job whose outcome
the test sets. Every call is recorded, so a test asserts the order of the calls
that matter: the release job, the check job, the scale-down, the catch-up job, the restore.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"
MIGRATE_PY = CI.parent.parent / "apps/api/scripts/migrate_conversations.py"
IMAGE = "ghcr.io/theexperiencecompany/gaia:2611.21.abc1234"
BACKEND = "gaia-prod_gaia-backend"
WORKER = "gaia-prod_arq_worker"
ENV_SECRET = "mongodb://user:hunter2@mongo/gaia"

TEMPLATE_ENV = ["ENV=production", f"MONGO_HINT={ENV_SECRET}"]
TEMPLATE = {
    "ContainerSpec": {
        "Image": "ghcr.io/theexperiencecompany/gaia:2611.20.old0000@sha256:aaa",
        "Dir": "/app/apps/api",
        "Env": TEMPLATE_ENV,
        "Secrets": [
            {
                "SecretName": "gaia_infisical_project_id",
                "File": {"Name": "gaia_infisical_project_id"},
            },
            {"SecretName": "gaia_metrics_token", "File": {"Name": "gaia_metrics_token"}},
        ],
    },
    "Networks": [{"Target": "net-shared"}, {"Target": "net-browser"}],
}

DOCKER_STUB = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

state = Path(os.environ["STATE"])
args = sys.argv[1:]
assert args[:2] == ["--context", "prod"], args
args = args[2:]
with (state / "calls").open("a") as log:
    log.write(json.dumps(args) + "\n")

def read(name, default=""):
    path = state / name
    return path.read_text().strip() if path.exists() else default

def running(svc):
    return int(read(f"running-{svc}", "0"))

if args[:2] == ["service", "inspect"]:
    svc, fmt = args[2], args[4]
    if fmt == "{{json .Spec.TaskTemplate}}":
        print(read("template"))
    elif fmt == "{{.Spec.Mode.Replicated.Replicas}}":
        print(read(f"replicas-{svc}"))
    else:
        sys.exit(f"unexpected inspect format {fmt}")
elif args[:2] == ["service", "create"]:
    name = args[args.index("--name") + 1]
    kind = args[args.index("--label") + 1].split("=", 1)[1]
    env_file = Path(args[args.index("--env-file") + 1])
    (state / f"env-{kind}").write_text(env_file.read_text())
    (state / f"writers-at-{kind}").write_text(
        json.dumps({s: running(s) for s in ("gaia-prod_gaia-backend", "gaia-prod_arq_worker")})
    )
    (state / f"job-{name}").write_text(kind)
elif args[:2] == ["service", "ps"] and "--quiet" in args:
    print(f"task-{args[2]}")
elif args[:2] == ["service", "ps"]:
    svc = args[2]
    lines = ["Shutdown 3 days ago"] + ["Running 2 hours ago"] * running(svc)
    print("\n".join(lines))
elif args[0] == "inspect":
    name = args[1].removeprefix("task-")
    kind = read(f"job-{name}")
    outcome = read(f"outcome-{kind}")
    if outcome.isdigit():
        state_name = "complete" if outcome == "0" else "failed"
        print(json.dumps({"State": state_name, "ContainerStatus": {"ExitCode": int(outcome)}}))
    elif outcome == "rejected":
        print(json.dumps({"State": "rejected", "Err": "No such image: gaia:2611.21.abc1234"}))
    else:
        print(json.dumps({"State": outcome}))
elif args[:2] == ["service", "scale"]:
    for pair in args[3:]:
        svc, replicas = pair.split("=")
        if read("writers-stuck") != "true":
            (state / f"running-{svc}").write_text(replicas)
elif args[:2] == ["service", "logs"]:
    print(f"log of {args[3]}")
elif args[:2] == ["service", "rm"]:
    pass
else:
    sys.exit(f"unexpected docker call: {args}")
"""


def _swarm(
    tmp_path: Path,
    *,
    check: str,
    release: str = "0",
    catch_up: str = "0",
    backend_replicas: int = 2,
    writers_stuck: bool = False,
) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    (state / "template").write_text(json.dumps(TEMPLATE))
    for svc, replicas in ((BACKEND, backend_replicas), (WORKER, 1)):
        (state / f"replicas-{svc}").write_text(str(replicas))
        (state / f"running-{svc}").write_text(str(replicas))
    (state / "outcome-release").write_text(release)
    (state / "outcome-check").write_text(check)
    (state / "outcome-catch-up").write_text(catch_up)
    (state / "writers-stuck").write_text("true" if writers_stuck else "false")
    return state


def _migrate(
    tmp_path: Path, state: Path, **env: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    output = tmp_path / "github_output"
    output.touch()
    result = subprocess.run(
        ["bash", str(SCRIPT), "migrate"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "GITHUB_OUTPUT": str(output),
            "GAIA_IMAGE_TAG": "2611.21.abc1234",
            "MIGRATE_POLL_SECS": "0",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calls = [json.loads(line) for line in (state / "calls").read_text().splitlines()]
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return result, calls, outputs


def _steps(calls: list[list[str]]) -> list[str]:
    """List the calls that change the Swarm, in order: job creates and removes, and scales."""
    steps: list[str] = []
    for call in calls:
        if call[:2] == ["service", "create"]:
            steps.append("create " + call[call.index("--label") + 1].split("=", 1)[1])
        elif call[:2] == ["service", "rm"]:
            job = re.fullmatch(r"gaia-migrate-(.+)-local-\d+", call[2])
            assert job, call
            steps.append("rm " + job.group(1))
        elif call[:2] == ["service", "scale"]:
            steps.append("scale " + " ".join(call[3:]))
    return steps


def _creates(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[:2] == ["service", "create"]]


def test_no_catch_up_needed_touches_no_writer(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="0")
    result, calls, outputs = _migrate(tmp_path, state)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _steps(calls) == ["create release", "rm release", "create check", "rm check"]
    assert outputs == {"catch_up": "none", "writers_down": "false"}


def test_a_needed_catch_up_runs_with_the_writers_stopped_and_leaves_them_down(
    tmp_path: Path,
) -> None:
    state = _swarm(tmp_path, check="3", catch_up="0")
    result, calls, outputs = _migrate(tmp_path, state)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _steps(calls) == [
        "create release",
        "rm release",
        "create check",
        "rm check",
        f"scale {BACKEND}=0 {WORKER}=0",
        "create catch-up",
        "rm catch-up",
    ]
    assert json.loads((state / "writers-at-catch-up").read_text()) == {BACKEND: 0, WORKER: 0}
    assert outputs == {"catch_up": "needed", "writers_down": "true"}


def test_a_failed_catch_up_restores_the_writers_replicas_and_fails(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="3", catch_up="1", backend_replicas=2)
    result, calls, outputs = _migrate(tmp_path, state)
    assert result.returncode != 0
    assert _steps(calls) == [
        "create release",
        "rm release",
        "create check",
        "rm check",
        f"scale {BACKEND}=0 {WORKER}=0",
        "create catch-up",
        "rm catch-up",
        f"scale {BACKEND}=2 {WORKER}=1",
    ]
    assert "the catch-up job failed (exit 1)" in result.stderr
    assert (state / f"running-{BACKEND}").read_text() == "2"
    assert "writers_down" not in outputs


def test_a_failed_release_step_stops_nothing_and_skips_the_check(tmp_path: Path) -> None:
    state = _swarm(tmp_path, release="1", check="3")
    result, calls, outputs = _migrate(tmp_path, state)
    assert result.returncode != 0
    assert _steps(calls) == ["create release", "rm release"]
    assert "the release's migrations failed (exit 1)" in result.stderr
    assert outputs == {}


def test_a_failed_check_stops_nothing(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="1")
    result, calls, _ = _migrate(tmp_path, state)
    assert result.returncode != 0
    assert _steps(calls) == ["create release", "rm release", "create check", "rm check"]
    assert "the check job failed (exit 1)" in result.stderr


def test_a_check_job_that_never_runs_names_the_task_error_and_is_removed(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="rejected")
    result, calls, _ = _migrate(tmp_path, state)
    assert result.returncode != 0
    assert _steps(calls) == ["create release", "rm release", "create check", "rm check"]
    assert "task rejected: No such image" in result.stderr


def test_a_job_past_its_timeout_fails_is_removed_and_restores_the_writers(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="3", catch_up="running")
    result, calls, _ = _migrate(tmp_path, state, MIGRATE_CATCH_UP_TIMEOUT_SECS="0")
    assert result.returncode != 0
    assert "did not finish within 0s (task running)" in result.stderr
    assert _steps(calls)[-2:] == ["rm catch-up", f"scale {BACKEND}=2 {WORKER}=1"]


def test_writers_that_do_not_stop_block_the_catch_up(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="3", writers_stuck=True)
    result, calls, _ = _migrate(tmp_path, state, MIGRATE_WRITERS_TIMEOUT_SECS="0")
    assert result.returncode != 0
    assert "not migrating under a live writer" in result.stderr
    assert "create catch-up" not in _steps(calls)
    assert _steps(calls)[-1] == f"scale {BACKEND}=2 {WORKER}=1"


def test_jobs_run_the_new_image_with_the_backends_secrets_networks_and_env(tmp_path: Path) -> None:
    state = _swarm(tmp_path, check="3", catch_up="0")
    result, calls, _ = _migrate(tmp_path, state)
    assert result.returncode == 0, result.stdout + result.stderr
    release, check, catch_up = _creates(calls)
    for create in (release, check, catch_up):
        assert create[create.index("--mode") : create.index("--mode") + 2] == [
            "--mode",
            "replicated-job",
        ]
        assert create[create.index("--restart-condition") + 1] == "none"
        assert create[create.index("--workdir") + 1] == "/app/apps/api"
        assert [create[i + 1] for i, a in enumerate(create) if a == "--secret"] == [
            "source=gaia_infisical_project_id,target=gaia_infisical_project_id",
            "source=gaia_metrics_token,target=gaia_metrics_token",
        ]
        assert [create[i + 1] for i, a in enumerate(create) if a == "--network"] == [
            "net-shared",
            "net-browser",
        ]
    assert release[release.index(IMAGE) :] == [
        IMAGE,
        "python",
        "-m",
        "scripts.post_deploy",
        "--apply",
    ]
    assert check[check.index(IMAGE) :] == [
        IMAGE,
        "python",
        "-m",
        "scripts.migrate_conversations",
        "--check",
    ]
    assert catch_up[catch_up.index(IMAGE) :] == [
        IMAGE,
        "python",
        "-m",
        "scripts.migrate_conversations",
    ]
    assert (state / "env-check").read_text().splitlines() == TEMPLATE_ENV
    assert ENV_SECRET not in json.dumps(calls) + result.stdout + result.stderr


def test_the_catch_up_needed_exit_code_matches_the_migration_script() -> None:
    shell = re.search(r"^_MIGRATE_CATCH_UP_NEEDED=(\d+)$", SCRIPT.read_text(), re.MULTILINE)
    python = re.search(r"^CATCH_UP_NEEDED_EXIT = (\d+)$", MIGRATE_PY.read_text(), re.MULTILINE)
    assert shell and python
    assert shell.group(1) == python.group(1)
