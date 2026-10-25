"""wait-swarm-convergence.sh: a service it cannot read is never converged.

``docker`` is a fake on PATH that answers from per-service files, so the real
script's polling loop runs without a Swarm. The defect this pins shipped: a
failed ``docker service inspect`` (a tailnet blip, a wrong service name) was
read as an empty update state, the empty state as "untouched", and the deploy
printed "All app services converged" on its first poll.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

CI = Path(__file__).parent.parent
SCRIPT = CI / "wait-swarm-convergence.sh"

DOCKER_STUB = """\
#!/usr/bin/env bash
# docker --context prod service <inspect|ps> gaia-prod_<svc> ...
svc="${5#gaia-prod_}"
dir="$STATE/$svc"
case "$4" in
  inspect)
    [ -d "$dir" ] || { echo "Error: no such service: $5" >&2; exit 1; }
    case "$*" in
      *UpdateStatus*)
        # A service the deploy left untouched has no UpdateStatus at all, and
        # docker's template errors on a field of the missing struct.
        if [ -f "$dir/state" ]; then cat "$dir/state"
        elif [[ "$*" == *"{{if .UpdateStatus}}"* ]]; then echo
        else echo 'template parsing error: nil pointer evaluating *swarm.UpdateStatus.State' >&2; exit 1
        fi ;;
      *Replicas*) cat "$dir/replicas" ;;
    esac ;;
  ps) cat "$dir/tasks" ;;
esac
"""


def _service(state_dir: Path, name: str, *, state: str | None, replicas: str, running: int) -> None:
    svc = state_dir / name
    svc.mkdir(parents=True)
    if state is not None:
        (svc / "state").write_text(state + "\n")
    (svc / "replicas").write_text(replicas + "\n")
    (svc / "tasks").write_text("Running 5 seconds ago\n" * running)


def _run(tmp_path: Path, *services: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), *services],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(tmp_path / "state"),
            "GITHUB_OUTPUT": str(tmp_path / "github_output"),
            "DEPLOY_CONVERGE_TIMEOUT": "0",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_completed_roll_at_full_replicas_converges(tmp_path: Path) -> None:
    _service(tmp_path / "state", "gaia-backend", state="completed", replicas="2", running=2)
    result = _run(tmp_path, "gaia-backend")
    assert result.returncode == 0, result.stderr
    assert "All app services converged" in result.stdout


def test_a_service_the_deploy_left_untouched_converges(tmp_path: Path) -> None:
    _service(tmp_path / "state", "gaia-backend", state=None, replicas="1", running=1)
    _service(tmp_path / "state", "arq_worker", state="completed", replicas="1", running=1)
    result = _run(tmp_path, "gaia-backend", "arq_worker")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "gaia-backend=1/1(untouched)" in result.stdout


def test_a_service_docker_cannot_inspect_fails_instead_of_converging(tmp_path: Path) -> None:
    _service(tmp_path / "state", "gaia-backend", state="completed", replicas="1", running=1)
    result = _run(tmp_path, "gaia-backend", "arq_worker")
    assert result.returncode != 0, result.stdout
    assert "converged" not in result.stdout
    assert "gaia-prod_arq_worker" in result.stdout + result.stderr


def test_a_roll_still_in_flight_times_out(tmp_path: Path) -> None:
    _service(tmp_path / "state", "gaia-backend", state="updating", replicas="1", running=1)
    result = _run(tmp_path, "gaia-backend")
    assert result.returncode == 1
    assert "timed_out=true" in (tmp_path / "github_output").read_text()
