"""deploy.sh retag rolled-back: :latest names exactly the image prod runs.

``docker`` is a fake on PATH: the stack's services and the image each one runs
come from files, and every ``imagetools create`` is recorded instead of pushed.
Two defects shipped here. Deduping on the full ``repo:tag@digest`` let two
services on one repo issue two retags, so a repo whose services disagreed had
its :latest left on whichever ref sorted last. And the service list named the
app and bot services but not grafana, so a grafana rollback left its :latest on
the build that had just been rolled away from.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"
NS = "ghcr.io/theexperiencecompany"

DOCKER_STUB = """\
#!/usr/bin/env bash
case "$*" in
  *"stack services"*) cat "$STATE/services" ;;
  *"service inspect"*) cat "$STATE/image-$5" ;;
  "buildx imagetools create -t "*) printf '%s %s\\n' "$5" "$6" >> "$STATE/retags" ;;
  *) echo "unexpected docker call: $*" >&2; exit 1 ;;
esac
"""


def _stack(tmp_path: Path, images: dict[str, str]) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    (state / "services").write_text("".join(f"gaia-prod_{name}\n" for name in images))
    for name, image in images.items():
        (state / f"image-gaia-prod_{name}").write_text(image + "\n")
    return state


def _retag(tmp_path: Path, state: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT), "retag", "rolled-back"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(state),
            "ROLLBACK_MODE": "last",
            "DOCKER_CONTEXT": "prod",
            "STACK": "gaia-prod",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    retags = state / "retags"
    return result, retags.read_text().splitlines() if retags.exists() else []


def test_services_sharing_a_digest_retag_their_repo_once(tmp_path: Path) -> None:
    state = _stack(
        tmp_path,
        {
            "gaia-backend": f"{NS}/gaia:2610.24.abc@sha256:aaa",
            "arq_worker": f"{NS}/gaia:latest@sha256:aaa",
        },
    )
    result, retags = _retag(tmp_path, state)
    assert result.returncode == 0, result.stdout + result.stderr
    assert retags == [f"{NS}/gaia:latest {NS}/gaia@sha256:aaa"]


def test_a_repo_whose_services_disagree_is_not_retagged(tmp_path: Path) -> None:
    state = _stack(
        tmp_path,
        {
            "gaia-backend": f"{NS}/gaia:2610.24.abc@sha256:aaa",
            "arq_worker": f"{NS}/gaia:2610.23.def@sha256:bbb",
        },
    )
    result, retags = _retag(tmp_path, state)
    assert result.returncode != 0
    assert retags == []
    assert "sha256:aaa" in result.stdout + result.stderr
    assert "sha256:bbb" in result.stdout + result.stderr


def test_grafana_and_bots_are_retagged_and_third_party_images_are_not(tmp_path: Path) -> None:
    state = _stack(
        tmp_path,
        {
            "grafana": f"{NS}/gaia-grafana:0123abc@sha256:ggg",
            "discord-bot": f"{NS}/gaia-bot-discord:2610.24.abc@sha256:ddd",
            "chromadb": "chromadb/chroma:1.5.1@sha256:ccc",
        },
    )
    result, retags = _retag(tmp_path, state)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(retags) == [
        f"{NS}/gaia-bot-discord:latest {NS}/gaia-bot-discord@sha256:ddd",
        f"{NS}/gaia-grafana:latest {NS}/gaia-grafana@sha256:ggg",
    ]


def test_a_stack_with_no_deployable_service_fails(tmp_path: Path) -> None:
    state = _stack(tmp_path, {"chromadb": "chromadb/chroma:1.5.1@sha256:ccc"})
    result, retags = _retag(tmp_path, state)
    assert result.returncode != 0
    assert retags == []
