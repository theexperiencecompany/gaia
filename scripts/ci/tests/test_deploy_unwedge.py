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

from dataclasses import dataclass
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


@dataclass
class Scenario:
    """What the stubbed GitHub API reports; None in place of data makes that request fail."""

    runs: dict[int, tuple[list[dict] | None, list[dict]]]
    # Run ids returned by each successive listing call; the last entry repeats.
    listings: list[list[int] | None] | None = None
    limit: int = LIMIT_SECS


@dataclass
class Outcome:
    proc: subprocess.CompletedProcess[str]
    posted: list[str]
    reaped: str | None


def run_unwedge(tmp_path: Path, scenario: Scenario) -> Outcome:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listings = scenario.listings if scenario.listings is not None else [list(scenario.runs)]
    for index, ids in enumerate(listings):
        if ids is not None:
            listing = {"workflow_runs": [{"id": run_id} for run_id in ids]}
            (tmp_path / f"runs-{index}.json").write_text(json.dumps(listing))
    for run_id, (pending, jobs) in scenario.runs.items():
        if pending is not None:
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
          *actions/runs\\?*)
            n=$(cat "{tmp_path}/listed" 2>/dev/null || echo 0)
            echo $((n + 1)) > "{tmp_path}/listed"
            (( n > {len(listings) - 1} )) && n={len(listings) - 1}
            src="{tmp_path}/runs-$n.json"
            ;;
          *) echo "unexpected gh api $url" >&2; exit 1 ;;
        esac
        [[ -f "$src" ]] || {{ echo "HTTP 502: $url" >&2; exit 1; }}
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
        "STUCK_LIMIT_SECS": str(scenario.limit),
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
    reaped = [
        line.removeprefix("reaped=")
        for line in output.read_text().splitlines()
        if line.startswith("reaped=")
    ]
    return Outcome(proc, posted, reaped[-1] if reaped else None)


def cancel_url(run_id: int) -> str:
    return f"repos/theexperiencecompany/gaia/actions/runs/{run_id}/force-cancel"


def test_unreleasable_gate_past_limit_is_force_cancelled(tmp_path: Path) -> None:
    out = run_unwedge(tmp_path, Scenario({37507260357: ([gate()], [waiting_job(ago(3 * 86400))])}))
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == [cancel_url(37507260357)]
    assert out.reaped == "37507260357"
    assert "::warning::" in out.proc.stderr


def test_gate_with_reviewers_is_a_real_approval_and_left_alone(tmp_path: Path) -> None:
    out = run_unwedge(
        tmp_path, Scenario({42: ([gate(reviewers=1)], [waiting_job(ago(3 * 86400))])})
    )
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == []
    assert out.reaped == ""


def test_gate_with_wait_timer_is_left_alone(tmp_path: Path) -> None:
    out = run_unwedge(
        tmp_path, Scenario({42: ([gate(wait_timer=30)], [waiting_job(ago(3 * 86400))])})
    )
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == []


def test_young_wedge_is_reaped_once_it_crosses_the_limit(tmp_path: Path) -> None:
    # A push that lands 10 min into a wedge must not exit and leave its own deploy queued behind it.
    out = run_unwedge(tmp_path, Scenario({42: ([gate()], [waiting_job(ago(1))])}, limit=3))
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == [cancel_url(42)]
    assert out.reaped == "42"


def test_young_gate_that_clears_while_waiting_is_not_reaped(tmp_path: Path) -> None:
    out = run_unwedge(
        tmp_path, Scenario({42: ([gate()], [waiting_job(ago(1))])}, listings=[[42], []], limit=3)
    )
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == []
    assert out.reaped == ""


def test_failed_listing_fails_loud(tmp_path: Path) -> None:
    out = run_unwedge(tmp_path, Scenario({}, listings=[None]))
    assert out.proc.returncode != 0
    assert "OK" not in out.proc.stdout


def test_reap_is_reported_even_when_a_later_request_fails(tmp_path: Path) -> None:
    out = run_unwedge(
        tmp_path,
        Scenario({8: ([gate()], [waiting_job(ago(86400))]), 9: (None, [waiting_job(ago(86400))])}),
    )
    assert out.proc.returncode != 0
    assert out.posted == [cancel_url(8)]
    assert out.reaped == "8"


def test_own_run_is_never_reaped(tmp_path: Path) -> None:
    out = run_unwedge(tmp_path, Scenario({OWN_RUN: ([gate()], [waiting_job(ago(3 * 86400))])}))
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == []


def test_waiting_run_without_a_deployment_gate_is_left_alone(tmp_path: Path) -> None:
    out = run_unwedge(tmp_path, Scenario({42: ([], [waiting_job(ago(3 * 86400))])}))
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == []


def test_only_the_wedged_run_is_reaped_among_several(tmp_path: Path) -> None:
    out = run_unwedge(
        tmp_path,
        Scenario(
            {
                7: ([gate(reviewers=2)], [waiting_job(ago(86400))]),
                8: ([gate()], [waiting_job(ago(86400))]),
            }
        ),
    )
    assert out.proc.returncode == 0, out.proc.stderr
    assert out.posted == [cancel_url(8)]
    assert out.reaped == "8"
