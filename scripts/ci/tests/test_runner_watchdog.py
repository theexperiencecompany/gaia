"""runner.sh watchdog decisions, driven through a stubbed ``gh``.

The watchdog exists to unpark a run whose home box died after ``select``
chose it. Two things it must NOT do, both of which it used to:

* exit on the first poll that lists no jobs — a lane whose ``needs:`` are
  unmet has no job record yet, so the watchdog was gone before the lanes it
  watches existed;
* cancel a run that ``select`` deliberately queued on a busy box
  (``online-busy-queued``), which is a normal, healthy state.

Every case here runs the real script; only ``gh`` is stubbed, so the jq
filters, the TSV parsing and the arithmetic are all exercised.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest

SCRIPT = Path(__file__).parent.parent / "runner.sh"
WATCHDOG = "Watch for a stalled home runner"


def ago(seconds: int) -> str:
    when = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def job(name: str, status: str, created: str, started: str = "", completed: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "created_at": created,
        "started_at": started or None,
        "completed_at": completed or None,
    }


@dataclass
class Scenario:
    """What the stubbed GitHub API reports for one watchdog run."""

    jobs: list[dict]
    run_status: str = "in_progress"
    runners: list[dict] = field(default_factory=list)
    runners_fail: bool = False
    limit: int = 480
    # After this many polls the stub reports the run completed, so a watchdog
    # that correctly keeps polling still terminates instead of hanging.
    polls_before_exit: int = 1


def run_watchdog(tmp_path: Path, scenario: Scenario) -> subprocess.CompletedProcess[str]:
    """Run the watchdog against the canned API responses in `scenario`."""
    run_status = scenario.run_status
    jobs = scenario.jobs
    runners = scenario.runners
    runners_fail = scenario.runners_fail
    limit = scenario.limit
    polls_before_exit = scenario.polls_before_exit
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    (tmp_path / "runners.json").write_text(json.dumps({"runners": runners or []}))

    stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Minimal `gh api` stand-in: routes on the URL, applies the real --jq
        # filter with jq so the script's filters are genuinely exercised.
        set -uo pipefail
        STATE="{tmp_path}/polls"
        url=""; jq_filter=""; method="GET"
        while [[ $# -gt 0 ]]; do
          case "$1" in
            api) ;;
            --jq) jq_filter="$2"; shift ;;
            -X) method="$2"; shift ;;
            --paginate) ;;
            *) [[ -z "$url" ]] && url="$1" ;;
          esac
          shift
        done
        if [[ "$method" == "POST" ]]; then
          echo cancel >> "{tmp_path}/cancelled"
          exit 0
        fi
        case "$url" in
          *actions/runners*)
            {"exit 1" if runners_fail else 'src="' + str(tmp_path) + '/runners.json"'}
            ;;
          */jobs*)  src="{tmp_path}/jobs.json" ;;
          *)
            n=$(cat "$STATE" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$STATE"
            if (( n > {polls_before_exit} )); then echo '"completed"' | jq -r "${{jq_filter:-.}}"
            else echo '{{"status":"{run_status}"}}' | jq -r "${{jq_filter:-.}}"; fi
            exit 0
            ;;
        esac
        jq -r "${{jq_filter:-.}}" < "$src"
        """
    )
    gh = bin_dir / "gh"
    gh.write_text(stub)
    gh.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "GITHUB_REPOSITORY": "theexperiencecompany/gaia",
        "GITHUB_RUN_ID": "1",
        "WATCHDOG_JOB_NAME": WATCHDOG,
        "QUEUE_LIMIT_SECS": str(limit),
        "POLL_SECS": "0",
        "RUNNER_LABEL": "gaia-home",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "watchdog"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,  # a cancel is exit 1, and that is one of the outcomes under test
    )


def cancelled(tmp_path: Path) -> bool:
    return (tmp_path / "cancelled").exists()


def test_no_jobs_yet_keeps_watching(tmp_path: Path) -> None:
    # Only the watchdog's own record exists: the lanes' `needs:` have not
    # resolved. It must not declare victory and leave.
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[job(WATCHDOG, "in_progress", ago(10), started=ago(10))],
            polls_before_exit=2,
        ),
    )
    assert "no lanes created yet" in proc.stdout
    assert "every lane was picked up" not in proc.stdout
    assert not cancelled(tmp_path)
    assert proc.returncode == 0


def test_dead_box_is_cancelled(tmp_path: Path) -> None:
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners=[{"status": "offline", "labels": [{"name": "gaia-home"}]}],
            limit=480,
        ),
    )
    assert cancelled(tmp_path)
    assert proc.returncode == 1
    assert "::error::" in proc.stdout


def test_busy_box_is_not_cancelled(tmp_path: Path) -> None:
    # select's online-busy-queued branch parks lanes on a busy box on purpose.
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners=[{"status": "online", "labels": [{"name": "gaia-home"}]}],
            limit=480,
            polls_before_exit=1,
        ),
    )
    assert not cancelled(tmp_path)
    assert "the box is busy, not dead" in proc.stderr
    assert proc.returncode == 0


def test_unreadable_runners_api_never_cancels(tmp_path: Path) -> None:
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners_fail=True,
            limit=480,
        ),
    )
    assert not cancelled(tmp_path)
    assert "not cancelling on an unknown" in proc.stderr
    assert proc.returncode == 0


def test_age_runs_from_eligibility_not_creation(tmp_path: Path) -> None:
    # `detect` finished 30 s ago, so `build` has only just become eligible —
    # its record being 900 s old is not evidence of a stall.
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[
                job("detect", "completed", ago(900), started=ago(880), completed=ago(30)),
                job("build", "queued", ago(900)),
            ],
            runners=[{"status": "offline", "labels": [{"name": "gaia-home"}]}],
            limit=480,
        ),
    )
    assert not cancelled(tmp_path)
    assert proc.returncode == 0
    assert "eligible for 3" in proc.stdout  # ~30s, not ~900s


def test_all_lanes_picked_up_exits_clean(tmp_path: Path) -> None:
    proc = run_watchdog(
        tmp_path,
        Scenario(
            jobs=[job("build", "in_progress", ago(100), started=ago(90))],
        ),
    )
    assert "every lane was picked up" in proc.stdout
    assert not cancelled(tmp_path)
    assert proc.returncode == 0


@pytest.mark.parametrize("terminal", ["completed", "cancelled", "failure"])
def test_finished_run_stops_watching(tmp_path: Path, terminal: str) -> None:
    proc = run_watchdog(
        tmp_path,
        Scenario(
            run_status=terminal,
            jobs=[job("build", "queued", ago(900))],
            polls_before_exit=0,
        ),
    )
    assert "nothing left to watch" in proc.stdout
    assert not cancelled(tmp_path)
    assert proc.returncode == 0
