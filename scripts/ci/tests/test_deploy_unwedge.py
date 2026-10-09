"""deploy.sh unwedge decisions, driven through a stubbed ``gh``.

Regression for run 37507260357: its swarm deploy sat in ``waiting`` on the
production environment for three days although that environment has no
reviewers and no wait timer, so nothing could ever release it. It held
build.yml's master concurrency group the whole time, and every later push's
image build queued behind it and was cancelled by the next one — four merges
never reached production with every gate green.

Only ``gh`` is stubbed: the jq filters, the age arithmetic and the
force-cancel decision all run for real.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import subprocess
import textwrap

SCRIPT = Path(__file__).parent.parent / "deploy.sh"
OWN_RUN = 1
LIMIT_SECS = 900


def ago(seconds: int) -> str:
    when = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def gate(reviewers: int = 0, wait_timer: int = 0) -> dict:
    return {
        "environment": {"name": "production"},
        "wait_timer": wait_timer,
        "reviewers": [{"type": "User", "reviewer": {"login": f"r{i}"}} for i in range(reviewers)],
    }


def waiting_job(started: str) -> dict:
    return {
        "name": "trigger-build / trigger-deploy / deploy",
        "status": "waiting",
        "started_at": started,
    }


def run_unwedge(
    tmp_path: Path, runs: dict[int, tuple[list[dict], list[dict]]]
) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
    """Run unwedge against `runs` ({run id: (pending deployments, jobs)})."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listing = {"workflow_runs": [{"id": run_id} for run_id in runs]}
    (tmp_path / "runs.json").write_text(json.dumps(listing))
    for run_id, (pending, jobs) in runs.items():
        (tmp_path / f"pending-{run_id}.json").write_text(json.dumps(pending))
        (tmp_path / f"jobs-{run_id}.json").write_text(json.dumps({"jobs": jobs}))

    stub = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -uo pipefail
        url=""; jq_filter=""; method="GET"
        while [[ $# -gt 0 ]]; do
          case "$1" in
            api) ;;
            --jq) jq_filter="$2"; shift ;;
            -X) method="$2"; shift ;;
            *) [[ -z "$url" ]] && url="$1" ;;
          esac
          shift
        done
        if [[ "$method" == "POST" ]]; then
          echo "$url" >> "{tmp_path}/posted"
          exit 0
        fi
        id=$(sed -E 's#.*/runs/([0-9]+)/.*#\\1#' <<< "$url")
        case "$url" in
          */pending_deployments) src="{tmp_path}/pending-$id.json" ;;
          */jobs*) src="{tmp_path}/jobs-$id.json" ;;
          *actions/runs\\?*) src="{tmp_path}/runs.json" ;;
          *) echo "unexpected gh api $url" >&2; exit 1 ;;
        esac
        jq -r "${{jq_filter:-.}}" < "$src"
        """
    )
    gh = bin_dir / "gh"
    gh.write_text(stub)
    gh.chmod(0o755)

    output = tmp_path / "github_output"
    output.touch()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "GITHUB_REPOSITORY": "theexperiencecompany/gaia",
        "GITHUB_RUN_ID": str(OWN_RUN),
        "GITHUB_OUTPUT": str(output),
        "STUCK_LIMIT_SECS": str(LIMIT_SECS),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "unwedge"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    posted_file = tmp_path / "posted"
    posted = posted_file.read_text().split() if posted_file.exists() else []
    return proc, posted, output.read_text()


def test_unreleasable_gate_past_limit_is_force_cancelled(tmp_path: Path) -> None:
    proc, posted, output = run_unwedge(
        tmp_path, {37507260357: ([gate()], [waiting_job(ago(3 * 86400))])}
    )
    assert proc.returncode == 0, proc.stderr
    assert posted == ["repos/theexperiencecompany/gaia/actions/runs/37507260357/force-cancel"]
    assert "reaped=37507260357" in output
    assert "::warning::" in proc.stderr


def test_gate_with_reviewers_is_a_real_approval_and_left_alone(tmp_path: Path) -> None:
    proc, posted, output = run_unwedge(
        tmp_path, {42: ([gate(reviewers=1)], [waiting_job(ago(3 * 86400))])}
    )
    assert proc.returncode == 0, proc.stderr
    assert posted == []
    assert "reaped=\n" in output


def test_gate_with_wait_timer_is_left_alone(tmp_path: Path) -> None:
    proc, posted, _ = run_unwedge(
        tmp_path, {42: ([gate(wait_timer=30)], [waiting_job(ago(3 * 86400))])}
    )
    assert proc.returncode == 0, proc.stderr
    assert posted == []


def test_gate_inside_limit_is_given_time(tmp_path: Path) -> None:
    proc, posted, _ = run_unwedge(tmp_path, {42: ([gate()], [waiting_job(ago(LIMIT_SECS - 60))])})
    assert proc.returncode == 0, proc.stderr
    assert posted == []


def test_own_run_is_never_reaped(tmp_path: Path) -> None:
    proc, posted, _ = run_unwedge(tmp_path, {OWN_RUN: ([gate()], [waiting_job(ago(3 * 86400))])})
    assert proc.returncode == 0, proc.stderr
    assert posted == []


def test_waiting_run_without_a_deployment_gate_is_left_alone(tmp_path: Path) -> None:
    proc, posted, _ = run_unwedge(tmp_path, {42: ([], [waiting_job(ago(3 * 86400))])})
    assert proc.returncode == 0, proc.stderr
    assert posted == []


def test_only_the_wedged_run_is_reaped_among_several(tmp_path: Path) -> None:
    proc, posted, output = run_unwedge(
        tmp_path,
        {
            7: ([gate(reviewers=2)], [waiting_job(ago(86400))]),
            8: ([gate()], [waiting_job(ago(86400))]),
            9: ([gate()], [waiting_job(ago(30))]),
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert posted == ["repos/theexperiencecompany/gaia/actions/runs/8/force-cancel"]
    assert "reaped=8" in output
