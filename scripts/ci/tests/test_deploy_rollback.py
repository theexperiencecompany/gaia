"""The smoke-triggered rollback: what it restores, what it leaves alone, and where it sits.

``docker`` is a fake on PATH whose services and images live in files, and whose
``service rollback`` swaps a service back to its recorded pre-deploy image the way
Swarm restores PreviousSpec. A second ``service rollback`` on the same service would
restore the bad spec again, so a re-run must roll back nothing, and a service the
deploy never changed must never be rolled back to an older spec.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

import yaml

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"
WORKFLOW = CI.parent.parent / ".github/workflows/deploy-swarm-prod.yml"
NS = "ghcr.io/theexperiencecompany"
OLD = f"{NS}/gaia:2611.22.aaaaaaa@sha256:old"
NEW = f"{NS}/gaia:2611.24.bbbbbbb@sha256:new"
BOT = f"{NS}/gaia-bot-discord:2611.01.ccccccc@sha256:bot"

DOCKER_STUB = """\
#!/usr/bin/env bash
case "$*" in
  "--context prod stack services "*) cat "$STATE/services" ;;
  "--context prod service inspect "*"Spec.Name"*) cat "$STATE/specs" ;;
  "--context prod service inspect "*) cat "$STATE/image-$5" ;;
  "--context prod service rollback "*)
    echo "$5" >> "$STATE/rolled"
    cp "$STATE/before-$5" "$STATE/image-$5" ;;
  "--context prod stack deploy "*) echo deployed >> "$STATE/deploys" ;;
  *) echo "unexpected docker call: $*" >&2; exit 1 ;;
esac
"""


def fake_docker(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    return bin_dir


def swarm(tmp_path: Path, now: dict[str, str], before: dict[str, str]) -> Path:
    """Services with the image each runs now and the one a rollback restores."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "services").write_text("".join(f"{name}\n" for name in now))
    for name, image in now.items():
        (state / f"image-{name}").write_text(image + "\n")
        (state / f"before-{name}").write_text(before.get(name, image) + "\n")
    return state


def deploy_sh(
    tmp_path: Path, state: Path, *args: str, cwd: Path | None = None, **env: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = tmp_path / "github_output"
    output.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={
            "PATH": f"{fake_docker(tmp_path)}:{os.environ['PATH']}",
            "STATE": str(state),
            "GITHUB_OUTPUT": str(output),
        }
        | env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return proc, outputs


def rolled(state: Path) -> list[str]:
    path = state / "rolled"
    return path.read_text().split() if path.exists() else []


def test_a_scoped_rollback_restores_only_what_the_deploy_changed(tmp_path: Path) -> None:
    state = swarm(
        tmp_path,
        now={
            "gaia-prod_gaia-backend": NEW,
            "gaia-prod_arq_worker": NEW,
            "gaia-prod_discord-bot": BOT,
        },
        before={"gaia-prod_gaia-backend": OLD, "gaia-prod_arq_worker": OLD},
    )
    rollback_from = (
        f"gaia-prod_gaia-backend={OLD} gaia-prod_arq_worker={OLD} gaia-prod_discord-bot={BOT}"
    )

    proc, outputs = deploy_sh(
        tmp_path,
        state,
        "rollback",
        ROLLBACK_MODE="last",
        ROLLBACK_SCOPED="true",
        ROLLBACK_FROM=rollback_from,
    )

    assert proc.returncode == 0, proc.stderr
    assert rolled(state) == ["gaia-prod_gaia-backend", "gaia-prod_arq_worker"]
    assert outputs["services"] == "gaia-prod_gaia-backend gaia-prod_arq_worker"
    assert "gaia-prod_discord-bot already runs its pre-deploy image" in proc.stderr


def test_rerunning_a_scoped_rollback_rolls_nothing_back_twice(tmp_path: Path) -> None:
    state = swarm(
        tmp_path, now={"gaia-prod_gaia-backend": NEW}, before={"gaia-prod_gaia-backend": OLD}
    )
    rollback_from = f"gaia-prod_gaia-backend={OLD}"

    first, _ = deploy_sh(
        tmp_path,
        state,
        "rollback",
        ROLLBACK_MODE="last",
        ROLLBACK_SCOPED="true",
        ROLLBACK_FROM=rollback_from,
    )
    second, _ = deploy_sh(
        tmp_path,
        state,
        "rollback",
        ROLLBACK_MODE="last",
        ROLLBACK_SCOPED="true",
        ROLLBACK_FROM=rollback_from,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode != 0
    assert rolled(state) == ["gaia-prod_gaia-backend"]
    assert "nothing to roll back" in second.stderr


def test_a_scoped_rollback_with_no_record_rolls_back_nothing(tmp_path: Path) -> None:
    state = swarm(
        tmp_path, now={"gaia-prod_gaia-backend": NEW}, before={"gaia-prod_gaia-backend": OLD}
    )

    proc, _ = deploy_sh(
        tmp_path, state, "rollback", ROLLBACK_MODE="last", ROLLBACK_SCOPED="true", ROLLBACK_FROM=""
    )

    assert proc.returncode != 0
    assert rolled(state) == []
    assert "not guessing which services to roll back" in proc.stderr


def test_a_dispatched_last_rollback_still_rolls_every_app_and_bot_service(tmp_path: Path) -> None:
    state = swarm(
        tmp_path,
        now={
            "gaia-prod_gaia-backend": NEW,
            "gaia-prod_discord-bot": BOT,
            "gaia-prod_redis": "redis:8",
        },
        before={"gaia-prod_gaia-backend": OLD},
    )

    proc, _ = deploy_sh(tmp_path, state, "rollback", ROLLBACK_MODE="last")

    assert proc.returncode == 0, proc.stderr
    assert rolled(state) == ["gaia-prod_gaia-backend", "gaia-prod_discord-bot"]


def test_the_stack_deploy_records_our_images_before_it_rolls(tmp_path: Path) -> None:
    state = swarm(tmp_path, now={"gaia-prod_gaia-backend": OLD}, before={})
    (state / "specs").write_text(
        f"gaia-prod_gaia-backend {OLD}\ngaia-prod_discord-bot {BOT}\ngaia-prod_redis redis:8.10.2-alpine\n"
    )
    infra = tmp_path / "work"
    obs = infra / ".infra/docker/observability"
    obs.mkdir(parents=True)
    for name in (
        "prometheus.yml",
        "loki-config.yaml",
        "promtail-config.yaml",
        "blackbox.yml",
        "rabbitmq-enabled-plugins",
    ):
        (obs / name).write_text(name)

    proc, outputs = deploy_sh(tmp_path, state, "stack", cwd=infra)

    assert proc.returncode == 0, proc.stderr
    assert outputs["images_before"] == f"gaia-prod_gaia-backend={OLD} gaia-prod_discord-bot={BOT}"
    assert (state / "deploys").read_text() == "deployed\n"


def _workflow() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return document


def _step_index(steps: list[dict[str, Any]], step_id: str) -> int:
    return next(i for i, step in enumerate(steps) if step.get("id") == step_id)


def test_the_smoke_runs_after_prod_serves_the_commit_and_before_latest_moves() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    smoke = _step_index(steps, "smoke")
    retag = next(
        i
        for i, step in enumerate(steps)
        if step.get("run") == "bash scripts/ci/deploy.sh retag from-env"
    )

    assert steps[smoke]["run"] == "bash scripts/ci/deploy.sh smoke"
    assert "continue-on-error" not in steps[smoke]
    assert _step_index(steps, "verify") < smoke < retag
    assert steps[retag]["if"].startswith("success()")


def test_a_failed_smoke_verdict_is_what_fires_the_rollback_job() -> None:
    jobs = _workflow()["jobs"]
    outputs = jobs["deploy"]["outputs"]
    rollback = jobs["rollback"]
    step = next(step for step in rollback["steps"] if step.get("id") == "rollback")

    assert "steps.smoke.outputs.verdict == 'fail'" in outputs["rollback"]
    assert "steps.migrate.outputs.writers_down != 'true'" in outputs["rollback"]
    assert outputs["rollback_from"] == "${{ steps.stack.outputs.images_before }}"
    assert rollback["needs"] == ["deploy"]
    assert "!cancelled()" in rollback["if"]
    assert "needs.deploy.outputs.rollback == 'true'" in rollback["if"]
    assert step["run"] == "bash scripts/ci/deploy.sh rollback"
    assert step["env"]["ROLLBACK_SCOPED"] == "${{ needs.deploy.outputs.rollback == 'true' }}"
    assert step["env"]["ROLLBACK_FROM"] == "${{ needs.deploy.outputs.rollback_from }}"


def test_the_rollback_is_smoked_before_it_claims_recovery() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    smoke = _step_index(steps, "smoke")
    recovered = next(
        i for i, step in enumerate(steps) if (step.get("env") or {}).get("STATE") == "recovered"
    )

    assert steps[smoke]["run"] == "bash scripts/ci/deploy.sh smoke"
    assert _step_index(steps, "rollback") < smoke < recovered
    assert steps[recovered]["if"] == "success()"
