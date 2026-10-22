"""runner.sh select's three-pool routing, driven through a stubbed ``curl``.

Two self-hosted boxes now serve CI: the x86_64 home server (RAM-heavy and
service-backed lanes, and everything that must be x86_64) and the arm64 M4
(compute-bound lanes). ``select`` answers three questions from one runners-API
fetch — where the general, the CPU-bound and the x86_64-only lanes go — and
each answer has to degrade on its own: a dead M4 must not take the home lanes
down with it, and an x86_64-only lane must never be handed to the M4.

Only ``curl`` is stubbed, so the jq parsing and the decision code are real.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest

SCRIPT = Path(__file__).parent.parent / "runner.sh"
REPO = "theexperiencecompany/gaia"
FALLBACK = '["ubuntu-latest"]'
HOME = '["self-hosted","gaia-home"]'
M4 = '["self-hosted","gaia-m4"]'


def runner(label: str, status: str = "online", busy: bool = False, n: int = 1) -> dict:
    return {
        "name": f"{label}-{n}",
        "status": status,
        "busy": busy,
        "os": "Linux",
        "labels": [{"name": "self-hosted"}, {"name": label}],
    }


def select(
    tmp_path: Path, runners: list[dict], **env: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "runners.json").write_text(json.dumps({"runners": runners}))
    # The real endpoint pages at 30 unless per_page is raised; the stub does
    # the same, so a script that forgets per_page loses the second pool.
    stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        url="${{@: -1}}"
        if [[ "$url" == *per_page=100* ]]; then
          cat "{tmp_path}/runners.json"
        else
          jq '.runners |= .[:30]' "{tmp_path}/runners.json"
        fi
        """
    )
    curl = bin_dir / "curl"
    curl.write_text(stub)
    curl.chmod(0o755)
    base = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "GITHUB_OUTPUT": "/dev/stdout",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_TOKEN": "stub-token",
        "PR_HEAD_REPO": REPO,
    }
    base.update(env)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "select"],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    return proc, out


def test_both_boxes_online_split_the_lanes(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-home"), runner("gaia-m4")])
    assert (out["runner"], out["reason"], out["is_self_hosted"]) == (HOME, "online-idle", "true")
    assert (out["runner_cpu"], out["runner_cpu_label"], out["cpu_is_self_hosted"]) == (
        M4,
        "gaia-m4",
        "true",
    )
    assert (out["runner_x64"], out["x64_is_self_hosted"]) == (HOME, "true")
    assert out["runner_labels"] == "gaia-home,gaia-m4"


def test_a_busy_m4_is_still_queued_on(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-home"), runner("gaia-m4", busy=True)])
    assert out["runner_cpu"] == M4


def test_home_offline_overflows_general_lanes_to_the_m4_but_never_x64(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-home", status="offline"), runner("gaia-m4")])
    assert (out["runner"], out["runner_label"], out["is_self_hosted"]) == (M4, "gaia-m4", "true")
    assert out["reason"].startswith("overflow-cpu-pool (home offline")
    assert out["runner_cpu"] == M4
    assert (out["runner_x64"], out["runner_x64_label"], out["x64_is_self_hosted"]) == (
        FALLBACK,
        "ubuntu-latest",
        "false",
    )
    assert out["runner_labels"] == "gaia-m4"


def test_home_not_registered_overflows_too(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-m4")])
    assert out["runner"] == M4
    assert out["reason"] == "overflow-cpu-pool (home not-registered)"


def test_m4_offline_leaves_every_lane_on_home(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-home"), runner("gaia-m4", status="offline")])
    assert out["runner"] == out["runner_cpu"] == out["runner_x64"] == HOME
    assert out["runner_cpu_label"] == "gaia-home"
    assert out["runner_labels"] == "gaia-home"


def test_m4_never_registered_is_the_pre_m4_behaviour(tmp_path: Path) -> None:
    _, out = select(tmp_path, [runner("gaia-home", busy=True)])
    assert (out["runner"], out["reason"]) == (HOME, "online-busy-queued")
    assert out["runner_cpu"] == out["runner_x64"] == HOME


def test_both_boxes_offline_fall_back_everywhere(tmp_path: Path) -> None:
    _, out = select(
        tmp_path, [runner("gaia-home", status="offline"), runner("gaia-m4", status="offline")]
    )
    assert out["runner"] == out["runner_cpu"] == out["runner_x64"] == FALLBACK
    assert (
        out["is_self_hosted"] == out["cpu_is_self_hosted"] == out["x64_is_self_hosted"] == "false"
    )
    assert out["reason"] == "offline (0/1 online)"
    assert out["runner_labels"] == ""


def test_force_home_still_fails_rather_than_overflowing(tmp_path: Path) -> None:
    # force_home is a smoke test of the HOME pool: landing on the M4 instead
    # would pass it without proving anything about home.
    proc, _ = select(
        tmp_path,
        [runner("gaia-home", status="offline"), runner("gaia-m4")],
        FORCE_HOME="true",
    )
    assert proc.returncode != 0


@pytest.mark.parametrize(
    "env",
    [
        {"PR_HEAD_REPO": "outsider/gaia"},
        {"PR_AUTHOR_ASSOCIATION": "CONTRIBUTOR"},
        {"GITHUB_ACTOR": "dependabot[bot]"},
        {"FORCE_GITHUB": "true"},
        {"GITHUB_TOKEN": ""},
    ],
)
def test_trust_gates_send_every_pool_to_the_fallback(tmp_path: Path, env: dict[str, str]) -> None:
    _, out = select(tmp_path, [runner("gaia-home"), runner("gaia-m4")], **env)
    assert out["runner"] == out["runner_cpu"] == out["runner_x64"] == FALLBACK
    assert out["cpu_is_self_hosted"] == out["x64_is_self_hosted"] == "false"
    assert out["runner_labels"] == ""


def test_a_benchmark_can_pin_every_arch_neutral_lane_to_the_m4(tmp_path: Path) -> None:
    _, out = select(
        tmp_path,
        [runner("gaia-home"), runner("gaia-m4")],
        RUNNER_LABEL="gaia-m4",
        CPU_RUNNER_LABEL="gaia-m4",
        FORCE_HOME="true",
    )
    assert out["runner"] == out["runner_cpu"] == M4
    assert out["runner_x64"] == HOME
    assert out["runner_labels"] == "gaia-m4,gaia-home"


def test_a_pool_past_the_first_api_page_is_still_seen(tmp_path: Path) -> None:
    home = [runner("gaia-home", busy=True, n=i) for i in range(30)]
    _, out = select(tmp_path, [*home, runner("gaia-m4")])
    assert out["runner_cpu"] == M4
