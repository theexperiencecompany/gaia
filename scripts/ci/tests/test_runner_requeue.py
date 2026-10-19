"""runner.sh requeue-stranded decisions, driven through a stubbed ``gh``.

"Re-run failed jobs" re-runs only the failed lanes, so they keep the home
runs-on that select chose the first time. With the home listeners offline they
queue forever: nothing in the run is left to notice. The sweep must cancel and
fully re-run exactly those attempts, and leave every other run alone.

Only ``gh`` is stubbed: the jq filters, the TSV parsing and the age arithmetic
are the real script's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import subprocess
import textwrap

SCRIPT = Path(__file__).parent.parent / "runner.sh"
HOME = ["self-hosted", "gaia-home"]


def ago(seconds: int) -> str:
    when = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def queued_job(name: str, labels: list[str], queued_for: int) -> dict:
    return {"name": name, "status": "queued", "labels": labels, "created_at": ago(queued_for)}


@dataclass
class Scenario:
    """What the stubbed GitHub API reports for one sweep."""

    jobs: list[dict]
    run_attempt: int = 2
    runners: list[dict] = field(
        default_factory=lambda: [{"status": "offline", "labels": [{"name": "gaia-home"}]}]
    )
    runners_fail: bool = False
    cancel_completes: bool = True


def sweep(tmp_path: Path, scenario: Scenario) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run requeue-stranded against `scenario`; return the result and the POSTs it made, in order."""
    (tmp_path / "runs.json").write_text(
        json.dumps({"workflow_runs": [{"id": 77, "run_attempt": scenario.run_attempt}]})
    )
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": scenario.jobs}))
    (tmp_path / "runners.json").write_text(json.dumps({"runners": scenario.runners}))
    run_status = "completed" if scenario.cancel_completes else "in_progress"
    runners = "exit 1" if scenario.runners_fail else f'src="{tmp_path}/runners.json"'
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # `gh api` stand-in: routes on the URL and applies the real --jq filter.
        set -uo pipefail
        url=""; jq_filter=""; method="GET"
        while [[ $# -gt 0 ]]; do
          case "$1" in
            api|--paginate) ;;
            --jq) jq_filter="$2"; shift ;;
            -X) method="$2"; shift ;;
            *) [[ -z "$url" ]] && url="$1" ;;
          esac
          shift
        done
        if [[ "$method" == "POST" ]]; then echo "$url" >> "{tmp_path}/posts"; exit 0; fi
        case "$url" in
          *actions/runners*) {runners} ;;
          *actions/runs\\?*status=queued*) src="{tmp_path}/runs.json" ;;
          *actions/runs\\?*) echo '{{"workflow_runs": []}}' | jq -r "$jq_filter"; exit 0 ;;
          */jobs*) src="{tmp_path}/jobs.json" ;;
          *) echo '{{"status": "{run_status}"}}' | jq -r "$jq_filter"; exit 0 ;;
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
        "QUEUE_LIMIT_SECS": "480",
        "CANCEL_WAIT_SECS": "0",
        "POLL_SECS": "0",
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "requeue-stranded"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,  # a cancel that never completes is exit 1, one of the outcomes under test
    )
    posts_file = tmp_path / "posts"
    posts = posts_file.read_text().split() if posts_file.exists() else []
    return proc, [post.rsplit("/", 1)[-1] for post in posts]


def test_a_stranded_rerun_is_cancelled_then_rerun_in_full(tmp_path: Path) -> None:
    proc, posts = sweep(tmp_path, Scenario(jobs=[queued_job("docker-image", HOME, 900)]))

    assert posts == ["cancel", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0


def test_an_online_home_runner_means_nothing_is_stranded(tmp_path: Path) -> None:
    proc, posts = sweep(
        tmp_path,
        Scenario(
            jobs=[queued_job("docker-image", HOME, 900)],
            runners=[{"status": "online", "labels": [{"name": "gaia-home"}]}],
        ),
    )

    assert posts == []
    assert proc.returncode == 0


def test_an_unknown_runner_probe_touches_nothing(tmp_path: Path) -> None:
    proc, posts = sweep(
        tmp_path, Scenario(jobs=[queued_job("docker-image", HOME, 900)], runners_fail=True)
    )

    assert posts == []
    assert proc.returncode == 0


def test_a_first_attempt_is_left_to_its_own_watchdog(tmp_path: Path) -> None:
    _, posts = sweep(
        tmp_path, Scenario(jobs=[queued_job("docker-image", HOME, 900)], run_attempt=1)
    )

    assert posts == []


def test_a_lane_queued_on_github_hosted_is_not_stranded(tmp_path: Path) -> None:
    _, posts = sweep(tmp_path, Scenario(jobs=[queued_job("lint", ["ubuntu-latest"], 900)]))

    assert posts == []


def test_a_lane_inside_the_queue_limit_is_left_alone(tmp_path: Path) -> None:
    _, posts = sweep(tmp_path, Scenario(jobs=[queued_job("docker-image", HOME, 60)]))

    assert posts == []


def test_a_cancel_that_never_completes_fails_loud_without_a_rerun(tmp_path: Path) -> None:
    proc, posts = sweep(
        tmp_path,
        Scenario(jobs=[queued_job("docker-image", HOME, 900)], cancel_completes=False),
    )

    assert posts == ["cancel"]
    assert proc.returncode == 1
    assert "::error::" in proc.stdout


def test_a_rerun_stranded_on_a_dead_m4_is_requeued_while_home_is_up(tmp_path: Path) -> None:
    # Each pool is swept on its own: an online home box cannot pick up a lane
    # that queued on the M4's label.
    proc, posts = sweep(
        tmp_path,
        Scenario(
            jobs=[queued_job("build", ["self-hosted", "gaia-m4"], 900)],
            runners=[
                {"status": "online", "labels": [{"name": "gaia-home"}]},
                {"status": "offline", "labels": [{"name": "gaia-m4"}]},
            ],
        ),
    )

    assert posts == ["cancel", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0
