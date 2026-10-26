"""runner.py health: which of the two queueing causes this box is in.

"Queued for six minutes" has two causes with opposite fixes — the box is
thrashing, or every GitHub listener is busy — and nothing printed both, so
they were guessed at. The API half is a local fake GitHub; the load, thread
count, CPU-slot pool and process counts are read from the machine the test
runs on, which is the point: they must be read, not invented.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path

from doc_shape import mapping
from github_fake import FakeGitHub, Reply, run_runner, runner
import pytest

RUNNERS = Reply(
    200,
    {
        "runners": [
            runner("home-1", "online", "gaia-home"),
            runner("home-2", "online", "gaia-home", busy=True),
            runner("home-3", "offline", "gaia-home"),
        ]
    },
)


@dataclass
class Health:
    """The probe and the pool it reads, so a test can seed one and run the other."""

    pool: Path
    run: Callable[..., dict[str, object]]


@pytest.fixture
def health(tmp_path: Path, github: FakeGitHub) -> Health:
    """Run runner.py health against a private pool and the fake GitHub."""
    pool = tmp_path / "pool"
    (pool / "holders").mkdir(parents=True)

    def run(*, runners: Reply = RUNNERS, **env: str) -> dict[str, object]:
        github.on("GET", r"/actions/runners$", runners)
        proc = run_runner(
            "health",
            env=github.env(GAIA_CPU_SLOTS_DIR=str(pool), GAIA_CPU_TOKENS="16", **env),
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        report: dict[str, object] = json.loads(proc.stdout)
        return report

    return Health(pool=pool, run=run)


def test_the_listener_pool_is_reported_as_online_busy_and_idle(health: Health) -> None:
    report = health.run()
    assert report["listeners"] == {"online": 2, "busy": 1, "idle": 1, "registered": 3}


def test_an_api_that_cannot_answer_leaves_the_pool_null_rather_than_zero(health: Health) -> None:
    """Zero online reads as "the box is dead"; unknown must not be mistaken for it."""
    report = health.run(runners=Reply(401, {"message": "Bad credentials"}))
    assert report["listeners"] == {"online": None, "busy": None, "idle": None, "registered": None}
    # Everything the box itself knows is still there.
    threads = report["threads"]
    assert isinstance(threads, int) and threads > 0
    assert set(mapping(report["loadavg"])) == {"1m", "5m", "15m"}


def test_a_live_cpu_slot_grant_is_counted_against_the_pool(health: Health) -> None:
    (health.pool / "holders" / f"{os.getpid()}.4242").write_text("6")
    report = health.run()
    slots = mapping(report["cpu_slots"])
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
    slots = mapping(report["cpu_slots"])
    assert slots["held"] == 0
    assert slots["available"] == 16
    assert [h["alive"] for h in slots["holders"]] == [False]


def test_the_report_counts_the_processes_that_actually_eat_the_box(health: Health) -> None:
    report = health.run()
    processes = mapping(report["processes"])
    assert set(processes) == {"mutmut", "pytest", "runner_listeners"}
    # This very test runs under pytest, so the count cannot be zero — which is
    # what proves the count is read rather than defaulted.
    assert processes["pytest"] >= 1


def test_health_never_writes_to_the_pool_it_reads(health: Health) -> None:
    (health.pool / "holders" / f"{os.getpid()}.1").write_text("3")
    health.run()
    assert [p.name for p in (health.pool / "holders").iterdir()] == [f"{os.getpid()}.1"]


def _path_without_listeners(tmp_path: Path) -> str:
    """Put a ps on PATH that lists no Runner.Listener, so only the runner name decides."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps = bin_dir / "ps"
    ps.write_text("#!/usr/bin/env bash\necho 'python -m pytest'\n")
    ps.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def test_a_box_runner_is_reported_as_the_runner_host(health: Health, tmp_path: Path) -> None:
    report = health.run(RUNNER_NAME="gaia-home-4", PATH=_path_without_listeners(tmp_path))
    assert report["is_runner_host"] is True


def test_a_blacksmith_runner_is_not_the_runner_host(health: Health, tmp_path: Path) -> None:
    """Blacksmith reports RUNNER_ENVIRONMENT=self-hosted too; only the box's name counts."""
    report = health.run(
        RUNNER_NAME="blacksmith-4vcpu-ubuntu-2404-1",
        RUNNER_ENVIRONMENT="self-hosted",
        PATH=_path_without_listeners(tmp_path),
    )
    assert report["is_runner_host"] is False
