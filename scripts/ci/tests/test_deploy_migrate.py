"""deploy.sh migrate: the release's migrations run as a one-off Swarm job before the stack rolls.

``docker`` is a fake on PATH: ``stack config`` prints a rendered stack shaped like
gaia-infra's, ``service ps`` walks the job's task through the states in a file, and
every create, log and remove is recorded instead of touching a swarm.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"

RENDERED_STACK = """\
services:
  arq_worker:
    image: ghcr.io/theexperiencecompany/gaia:2611.18.abc1234
    working_dir: /app/apps/api
    command: [python, -m, arq, app.worker.WorkerSettings]
    environment:
      ENV: production
      GAIA_SERVICE_NAME: arq_worker
      PYTHONPATH: /app/apps/api
      ARQ_METRICS_PORT: "9100"
    secrets:
      - source: gaia_infisical_project_id
        target: gaia_infisical_project_id
      - source: gaia_metrics_token
        target: gaia_metrics_token
    networks:
      gaia-browser-net: null
      gaia-prod-shared:
        aliases: [arq_worker]
    volumes:
      - type: volume
        source: gaia_jfs_v2
        target: /mnt/jfs
        volume:
          nocopy: true
    deploy:
      placement:
        constraints: [node.role == manager]
networks:
  gaia-browser-net:
    driver: overlay
  gaia-prod-shared:
    external: true
    name: gaia-prod-shared
volumes:
  gaia_jfs_v2:
    external: true
    name: gaia_jfs_v2
"""

DOCKER_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$STATE/calls"
case "$*" in
  *"stack config"*) cat "$STATE/rendered" ;;
  *"service inspect"*) [[ -f "$STATE/earlier-job" ]] ;;
  *"service create"*) printf '%s\\n' "$@" > "$STATE/created" ;;
  *"service ps"*)
    head -n 1 "$STATE/states"
    if [[ $(wc -l < "$STATE/states") -gt 1 ]]; then sed -i.bak 1d "$STATE/states"; fi ;;
  *"service logs"*) echo "  migrate_briefing_state: applied" ;;
  *"service rm"*) rm -f "$STATE/earlier-job" ;;
  *) echo "unexpected docker call: $*" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def yq() -> str:
    path = shutil.which("yq")
    # A version manager's shim can be on PATH with no yq behind it.
    version = (
        subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
        if path
        else None
    )
    if path is None or version is None or "mikefarah" not in version.stdout:
        pytest.skip("yq (mikefarah, as on GitHub's runners) is not installed")
    return path


def _migrate(
    tmp_path: Path, states: list[str], *, earlier_job: bool = False, timeout_secs: int = 30
) -> tuple[subprocess.CompletedProcess[str], Path]:
    state = tmp_path / "state"
    state.mkdir()
    (state / "rendered").write_text(RENDERED_STACK)
    (state / "states").write_text("\n".join(states) + "\n")
    if earlier_job:
        (state / "earlier-job").touch()
    obs = tmp_path / ".infra/docker/observability"
    obs.mkdir(parents=True)
    for name in (
        "prometheus.yml",
        "loki-config.yaml",
        "promtail-config.yaml",
        "blackbox.yml",
        "rabbitmq-enabled-plugins",
    ):
        (obs / name).write_text(name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT), "migrate"],
        cwd=tmp_path,
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "MIGRATE_POLL_SECS": "0.1",
            "MIGRATE_TIMEOUT_SECS": str(timeout_secs),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, state


def _created(state: Path) -> list[str]:
    return (state / "created").read_text().splitlines()


def _after(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == flag]


@pytest.mark.usefixtures("yq")
def test_the_job_is_the_workers_image_running_the_release_step(tmp_path: Path) -> None:
    result, state = _migrate(tmp_path, ["Pending", "Running 1 second ago", "Complete now"])

    assert result.returncode == 0, result.stdout + result.stderr
    args = _created(state)
    assert args[-5:] == [
        "ghcr.io/theexperiencecompany/gaia:2611.18.abc1234",
        "python",
        "-m",
        "scripts.post_deploy",
        "--apply",
    ]
    assert "replicated-job" in args
    assert _after(args, "--restart-condition") == ["none"]
    assert _after(args, "--workdir") == ["/app/apps/api"]
    assert _after(args, "--env") == [
        "GAIA_SERVICE_NAME=migrate",
        "ENV=production",
        "PYTHONPATH=/app/apps/api",
        "ARQ_METRICS_PORT=9100",
    ]
    assert _after(args, "--secret") == ["gaia_infisical_project_id", "gaia_metrics_token"]
    assert _after(args, "--network") == ["gaia-prod-shared"]
    assert _after(args, "--mount") == [
        "type=volume,source=gaia_jfs_v2,target=/mnt/jfs,volume-nocopy=true"
    ]
    assert _after(args, "--constraint") == ["node.role == manager"]
    assert "migrate_briefing_state: applied" in result.stdout
    assert "service rm gaia-prod_migrate" in (state / "calls").read_text()


@pytest.mark.usefixtures("yq")
def test_a_failed_job_fails_the_step_and_is_removed(tmp_path: Path) -> None:
    result, state = _migrate(tmp_path, ["Running 1 second ago", "Failed 1 second ago"])

    assert result.returncode == 1
    assert "migrations failed" in result.stdout
    assert "service rm gaia-prod_migrate" in (state / "calls").read_text()


@pytest.mark.usefixtures("yq")
def test_a_job_still_running_at_the_deadline_is_left_running(tmp_path: Path) -> None:
    result, state = _migrate(tmp_path, ["Running 1 second ago"], timeout_secs=1)

    assert result.returncode == 1
    assert "left running" in result.stdout
    assert "service rm" not in (state / "calls").read_text()


@pytest.mark.usefixtures("yq")
def test_an_earlier_job_is_waited_for_never_killed(tmp_path: Path) -> None:
    result, state = _migrate(tmp_path, ["Running 1 second ago", "Complete now"], earlier_job=True)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = (state / "calls").read_text().splitlines()
    first_rm = next(i for i, call in enumerate(calls) if "service rm" in call)
    create = next(i for i, call in enumerate(calls) if "service create" in call)
    ps_before_rm = [call for call in calls[:first_rm] if "service ps" in call]
    assert len(ps_before_rm) == 2
    assert first_rm < create
