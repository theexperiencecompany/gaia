"""runner.sh health: which of the two queueing causes this box is in.

"Queued for six minutes" has two causes with opposite fixes — the box is
thrashing, or every GitHub listener is busy — and nothing printed both, so
they were guessed at. The API half is stubbed here (a real `gh` would answer
about the real repo); the load, thread count, CPU-slot pool and process counts
are read from the machine the test runs on, which is the point: they must be
read, not invented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "runner.sh"

RUNNERS_JSON = json.dumps(
    {
        "runners": [
            {
                "name": "home-1",
                "status": "online",
                "busy": False,
                "os": "linux",
                "labels": [{"name": "self-hosted"}, {"name": "gaia-home"}],
            },
            {
                "name": "home-2",
                "status": "online",
                "busy": True,
                "os": "linux",
                "labels": [{"name": "self-hosted"}, {"name": "gaia-home"}],
            },
            {
                "name": "home-3",
                "status": "offline",
                "busy": False,
                "os": "linux",
                "labels": [{"name": "self-hosted"}, {"name": "gaia-home"}],
            },
        ]
    }
)


@dataclass
class Health:
    """The probe and the pool it reads, so a test can seed one and run the other."""

    pool: Path
    run: Callable[..., dict]


@pytest.fixture
def health(tmp_path: Path) -> Health:
    """Run `runner.sh health` against a private pool and a stubbed `gh`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pool = tmp_path / "pool"
    (pool / "holders").mkdir(parents=True)

    def run(*, gh_body: str = f"cat <<'EOF'\n{RUNNERS_JSON}\nEOF") -> dict:
        stub = bin_dir / "gh"
        stub.write_text(f"#!/usr/bin/env bash\n{gh_body}\n")
        stub.chmod(0o755)
        proc = subprocess.run(
            ["bash", str(SCRIPT), "health"],
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": os.environ.get("HOME", "/tmp"),
                "GAIA_CPU_SLOTS_DIR": str(pool),
                "GAIA_CPU_TOKENS": "16",
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return json.loads(proc.stdout)

    return Health(pool=pool, run=run)


def test_the_listener_pool_is_reported_as_online_busy_and_idle(health: Health) -> None:
    report = health.run()
    assert report["listeners"] == {"online": 2, "busy": 1, "idle": 1, "registered": 3}


def test_a_gh_that_cannot_answer_leaves_the_pool_null_rather_than_zero(health: Health) -> None:
    """Zero online reads as "the box is dead"; unknown must not be mistaken for it."""
    report = health.run(gh_body="exit 1")
    assert report["listeners"] == {"online": None, "busy": None, "idle": None, "registered": None}
    # Everything the box itself knows is still there.
    assert report["threads"] > 0
    assert set(report["loadavg"]) == {"1m", "5m", "15m"}


def test_a_live_cpu_slot_grant_is_counted_against_the_pool(health: Health) -> None:
    (health.pool / "holders" / f"{os.getpid()}.4242").write_text("6")
    report = health.run()
    slots = report["cpu_slots"]
    assert slots["total"] == 16
    assert slots["held"] == 6
    assert slots["available"] == 10
    holder = next(h for h in slots["holders"] if h["pid"] == str(os.getpid()))
    assert holder["tokens"] == 6
    assert holder["alive"] is True


def test_a_grant_whose_holder_is_gone_is_shown_but_not_counted(health: Health) -> None:
    """A SIGKILLed job leaks its holder file; reading it as held hides real capacity."""
    (health.pool / "holders" / "999999999.1").write_text("8")
    report = health.run()
    slots = report["cpu_slots"]
    assert slots["held"] == 0
    assert slots["available"] == 16
    assert [h["alive"] for h in slots["holders"]] == [False]


def test_the_report_counts_the_processes_that_actually_eat_the_box(health: Health) -> None:
    report = health.run()
    assert set(report["processes"]) == {"mutmut", "pytest", "runner_listeners"}
    # This very test runs under pytest, so the count cannot be zero — which is
    # what proves the count is read rather than defaulted.
    assert report["processes"]["pytest"] >= 1


def test_health_never_writes_to_the_pool_it_reads(health: Health) -> None:
    (health.pool / "holders" / f"{os.getpid()}.1").write_text("3")
    health.run()
    assert [p.name for p in (health.pool / "holders").iterdir()] == [f"{os.getpid()}.1"]


def test_an_unknown_subcommand_still_prints_the_whole_usage_block() -> None:
    """usage() used to print a hardcoded line range that the header outgrew."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), "no-such-subcommand"],
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 2
    for subcommand in ("select", "parallel", "with-slots", "health"):
        assert subcommand in proc.stderr, f"usage does not reach '{subcommand}'"
    assert "set -euo pipefail" not in proc.stderr
