"""test-services.sh: topology choice, reconciliation and namespace hygiene.

``docker`` and ``curl`` are stubbed with recorders, so these exercise the real
script — its fingerprinting, its flock-guarded reconcile loop and its SQL —
without a Docker daemon. Each test names a defect that shipped:

* teardown ran from ``if: always()`` on lanes that never started services and
  hard-failed, reddening green lanes;
* ``up`` never reconciled a running container against changed flags, so a
  Postgres started with ``max_connections=300`` kept serving a suite that had
  since been sized for 1200;
* ``reset`` is best-effort and a cancelled job never runs it at all, yet
  ``prepare`` trusted the namespace it inherited to be clean;
* the five service image digests lived in three files at once.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

CI = Path(__file__).parent.parent
SCRIPT = CI / "test-services.sh"

DOCKER_STUB = """\
#!/usr/bin/env bash
# A small fake, not just a recorder: `run` remembers the config label it was
# given per container and `inspect` hands it back, so the script's reconcile
# loop is exercised for real. $REC/running flips liveness for every container.
printf '%s\\n' "$*" >> "$REC/docker.log"
case "$1" in
  inspect)
    name="${!#}"
    case "$*" in
      *State.Running*) cat "$REC/running" 2>/dev/null || echo true ;;
      *gaia.ci.config*) cat "$REC/label-$name" 2>/dev/null || true ;;
    esac
    exit 0 ;;
  run)
    name=""; label=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --name) name="$2"; shift ;;
        --label) label="${2#gaia.ci.config=}"; shift ;;
      esac
      shift
    done
    [[ -n "$name" ]] && printf '%s\\n' "$label" > "$REC/label-$name"
    echo "container-id"; exit 0 ;;
  pull|logs) exit 0 ;;
  rm)
    for a in "$@"; do rm -f "$REC/label-$a"; done
    exit 0 ;;
  exec)
    # psql SELECT-1 existence probe answers "1"; everything else just succeeds.
    case "$*" in *"SELECT 1 FROM pg_database"*) echo 1 ;; esac
    exit 0 ;;
esac
exit 0
"""

CURL_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REC/curl.log"
case "$*" in
  *heartbeat*) echo '{"nanosecond heartbeat":1}'; exit 0 ;;
  *collections*limit*) echo '[]'; exit 0 ;;
esac
exit 0
"""


def make_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("docker", DOCKER_STUB), ("curl", CURL_STUB)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "REC": str(tmp_path),
        "GAIA_CI_RUNDIR": str(tmp_path),
        "RUNNER_INDEX": "3",
    }
    env.update(extra)
    return env


def run(tmp_path: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=make_env(tmp_path, **extra),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=CI.parent.parent,
    )


def docker_log(tmp_path: Path) -> str:
    log = tmp_path / "docker.log"
    return log.read_text() if log.exists() else ""


# --- teardown must never red a green lane -----------------------------------


def test_reset_without_services_warns_and_succeeds(tmp_path: Path) -> None:
    # unit-a / unit-b run with services: "false" and never call `up`, yet their
    # `if: always()` teardown still calls reset.
    (tmp_path / "running").write_text("false\n")
    proc = run(tmp_path, "reset", RUNNER_ENVIRONMENT="self-hosted")
    assert proc.returncode == 0
    assert "nothing to reset" in proc.stderr


def test_janitor_without_services_succeeds(tmp_path: Path) -> None:
    (tmp_path / "running").write_text("false\n")
    proc = run(tmp_path, "janitor", RUNNER_ENVIRONMENT="self-hosted")
    assert proc.returncode == 0


def test_down_off_the_box_removes_this_jobs_containers(tmp_path: Path) -> None:
    proc = run(tmp_path, "down", RUNNER_ENVIRONMENT="github-hosted")
    assert proc.returncode == 0
    assert "gaia-test-postgres-3" in docker_log(tmp_path)


# --- topology is decided by the script, not the caller ----------------------


def test_self_hosted_uses_the_shared_set(tmp_path: Path) -> None:
    proc = run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    assert "shared set (self-hosted)" in proc.stdout
    assert "25432" in proc.stdout  # the shared Postgres port


def test_github_hosted_uses_per_job_containers(tmp_path: Path) -> None:
    proc = run(tmp_path, "up", RUNNER_ENVIRONMENT="github-hosted")
    assert "per-job containers" in proc.stdout
    assert "5732" in proc.stdout  # 5432 + RUNNER_INDEX(3) * 100


# --- up reconciles a running container against changed flags ----------------


def test_up_is_a_noop_when_the_config_fingerprint_matches(tmp_path: Path) -> None:
    first = run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    assert first.returncode == 0
    (tmp_path / "docker.log").unlink()
    second = run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    assert "already healthy" in second.stdout
    assert "\nrun " not in "\n" + docker_log(tmp_path)


def test_up_recreates_a_container_started_with_stale_flags(tmp_path: Path) -> None:
    # A Postgres still running with the old max_connections must be replaced,
    # not left serving a suite sized for the new one.
    run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    (tmp_path / "label-gaia-shared-postgres").write_text("stale-fingerprint\n")
    (tmp_path / "docker.log").unlink()
    proc = run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    assert proc.returncode == 0
    assert "gaia-shared-postgres: running with stale configuration" in proc.stderr
    log = docker_log(tmp_path)
    assert "rm -f gaia-shared-postgres" in log
    assert "max_connections=1200" in log
    # Only the drifted container is touched; the others keep serving.
    assert "rm -f gaia-shared-redis" not in log


def test_the_fingerprint_covers_the_flags_not_just_the_image(tmp_path: Path) -> None:
    # Same images, different max_connections => different fingerprint, so a
    # flag bump actually reconciles instead of looking identical.
    run(tmp_path, "up", RUNNER_ENVIRONMENT="self-hosted")
    label_a = (tmp_path / "label-gaia-shared-postgres").read_text().strip()
    (tmp_path / "docker.log").unlink()
    proc = run(
        tmp_path,
        "up",
        RUNNER_ENVIRONMENT="self-hosted",
        GAIA_SHARED_PG_MAX_CONNECTIONS="999",
    )
    assert proc.returncode == 0
    label_b = (tmp_path / "label-gaia-shared-postgres").read_text().strip()
    assert label_a != label_b
    assert "max_connections=999" in docker_log(tmp_path)


# --- prepare cleans the namespace instead of trusting reset -----------------


def test_prepare_drops_and_recreates_the_lane_database(tmp_path: Path) -> None:
    proc = run(tmp_path, "prepare", "4", RUNNER_ENVIRONMENT="self-hosted")
    assert proc.returncode == 0
    log = docker_log(tmp_path)
    assert "DROP DATABASE IF EXISTS gaia_test_r4 WITH (FORCE)" in log
    assert "CREATE DATABASE gaia_test_r4 OWNER gaia" in log


def test_prepare_clears_the_other_four_namespaces(tmp_path: Path) -> None:
    proc = run(tmp_path, "prepare", "4", RUNNER_ENVIRONMENT="self-hosted")
    assert proc.returncode == 0
    log = docker_log(tmp_path)
    assert "flushdb" in log  # Redis stripe
    assert "gaia_test_r4_" in log  # Mongo worker databases
    assert "delete_vhost r4" in log  # RabbitMQ, before add_vhost
    assert "add_vhost r4" in log
    assert (tmp_path / "curl.log").read_text().count("collections") >= 1  # Chroma


def test_prepare_writes_the_lane_env_contract(tmp_path: Path) -> None:
    gh_env = tmp_path / "github.env"
    gh_env.touch()
    proc = run(
        tmp_path,
        "prepare",
        "4",
        RUNNER_ENVIRONMENT="self-hosted",
        GITHUB_ENV=str(gh_env),
    )
    assert proc.returncode == 0
    written = (tmp_path / "gaia-test-services-4.env").read_text()
    exported = gh_env.read_text()
    for key in (
        "DATABASE_URL=postgresql://gaia:gaia@localhost:25432/gaia_test_r4",
        "GAIA_REDIS_DB_BASE=136",  # 8 + 4 * 32
        "GAIA_CHROMA_COLLECTION_SUFFIX=_r4",
        "RABBITMQ_URL=amqp://guest:guest@localhost:25673/r4",
    ):
        assert key in written
        assert key in exported


def test_perjob_prepare_publishes_endpoints_without_the_bookkeeping_list(
    tmp_path: Path,
) -> None:
    gh_env = tmp_path / "github.env"
    gh_env.touch()
    proc = run(
        tmp_path,
        "prepare",
        RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_ENV=str(gh_env),
    )
    assert proc.returncode == 0
    written = (tmp_path / "gaia-test-services-3.env").read_text()
    assert "GAIA_TEST_CONTAINERS=" in written
    assert "GAIA_TEST_CONTAINERS=" not in gh_env.read_text()
    assert "DATABASE_URL=postgresql://gaia:gaia@localhost:5732/gaia_test" in gh_env.read_text()


# --- the RabbitMQ probe that a root exec poisons ----------------------------


def test_rabbitmq_is_always_execed_as_the_rabbitmq_user(tmp_path: Path) -> None:
    # A plain exec runs as root, creates a root-owned .erlang.cookie during
    # boot and crashes the server with eacces (docker-library/rabbitmq#318).
    run(tmp_path, "prepare", "4", RUNNER_ENVIRONMENT="self-hosted")
    run(tmp_path, "reset", "4", RUNNER_ENVIRONMENT="self-hosted")
    for line in docker_log(tmp_path).splitlines():
        if "gaia-shared-rabbitmq" in line and line.startswith("exec"):
            assert "-u rabbitmq" in line, line


# --- one home for the image pins --------------------------------------------


def test_service_image_digests_live_in_exactly_one_place(tmp_path: Path) -> None:
    repo = CI.parent.parent
    holders = set()
    for path in repo.glob("scripts/**/*.sh"):
        if "sha256:" in path.read_text() and "_IMAGE=" in path.read_text():
            holders.add(path.relative_to(repo).as_posix())
    assert holders == {"scripts/ci/lib/service-images.sh"}, holders


@pytest.mark.parametrize(
    "image",
    ["POSTGRES_IMAGE", "REDIS_IMAGE", "MONGO_IMAGE", "CHROMA_IMAGE", "RABBITMQ_IMAGE"],
)
def test_dagger_pins_match_the_shared_source(image: str) -> None:
    # .dagger is the one deliberate second copy (the local harness must give a
    # dev machine the same topology); it may not drift.
    repo = CI.parent.parent
    pins = dict(
        line.split("=", 1)
        for line in (CI / "lib" / "service-images.sh").read_text().splitlines()
        if line.startswith(tuple(f"{k}=" for k in [image]))
    )
    digest = pins[image].strip('"').split("@")[1]
    dagger = (repo / ".dagger/src/gaia_ci/main.py").read_text()
    assert digest in dagger, f"{image} digest missing from .dagger"


def test_shell_is_syntactically_valid() -> None:
    assert (
        subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, check=False).returncode
        == 0
    )


def test_usage_on_unknown_subcommand(tmp_path: Path) -> None:
    proc = run(tmp_path, "nope")
    assert proc.returncode == 2
    assert "Usage: test-services.sh" in proc.stderr
