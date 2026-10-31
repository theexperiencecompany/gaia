"""deploy.sh notify's structured messages, and failing-checks' cause lookup.

CI messages were prose blobs: no cause, no action, one essay per master run.
A message is now a state (deploy_blocked, deploy_failed, deploy_succeeded,
recovered), its impact, the cause, the action and what clears it — eight content
lines at most. These tests pin the shape each state renders, the line budget
that refuses a drifting template in the run rather than in Slack, the legacy
MESSAGE path (still has callers), and failing-checks, whose empty answer would
otherwise read exactly like "nothing failed".

Only ``gh`` is stubbed; the jq filter that decides what counts as a failing
check runs for real, through the stub, exactly as on a runner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml

CI = Path(__file__).parent.parent
SCRIPT = CI / "deploy.sh"
WORKFLOW = CI.parent.parent / ".github/workflows/deploy-swarm-prod.yml"
SHA = "d980793b0c1e2f3a4b5c6d7e8f9012345678abcd"
STATES = ("deploy_blocked", "deploy_failed", "deploy_succeeded", "recovered")

BLOCKED = {
    "STATE": "deploy_blocked",
    "SUBJECT": "prod is 3 commits behind master",
    "IMPACT": "fine, serving fc67d3d8. Nothing is broken; new work isn't live.",
    "CAUSE": "ci / security / pip-audit failed on d980793b\n→ https://example.test/runs/1",
    "ACTION": "fix pyasn1 — #1564 is queued.",
    "CLEARS_WHEN": "master's quality-gate goes green.",
}


def run(
    sub: str, env: dict[str, str], *args: str, bin_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a deploy.sh subcommand in a hermetic environment, rendering but never delivering."""
    path = os.environ["PATH"] if bin_dir is None else f"{bin_dir}:{os.environ['PATH']}"
    return subprocess.run(
        ["bash", str(SCRIPT), sub, *args],
        env={"PATH": path, "HOME": os.environ.get("HOME", "/tmp"), "DRY_RUN": "true"} | env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def notify(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return run("notify", env)


def body(proc: subprocess.CompletedProcess[str]) -> list[str]:
    """Return the rendered message, without notify's own dry-run verdict."""
    lines = proc.stdout.splitlines()
    start = lines.index("Deploy notification:") + 1
    return [line for line in lines[start:] if not line.startswith("deploy notify:")]


def content_lines(lines: list[str]) -> int:
    return len([line for line in lines if line.strip()])


def test_blocked_renders_state_impact_cause_action_and_clear(tmp_path: Path) -> None:
    proc = notify(BLOCKED)

    assert proc.returncode == 0, proc.stderr
    assert body(proc) == [
        "⛔ DEPLOY BLOCKED — prod is 3 commits behind master",
        "Prod: fine, serving fc67d3d8. Nothing is broken; new work isn't live.",
        "",
        "Cause: ci / security / pip-audit failed on d980793b",
        "        → https://example.test/runs/1",
        "Do: fix pyasn1 — #1564 is queued.",
        "Clears when: master's quality-gate goes green.",
    ]


def test_a_field_ending_in_a_newline_adds_no_blank_line() -> None:
    """Keep a field's trailing newline out of the rendered message.

    A YAML block scalar keeps its trailing newline; it must not become an
    indented whitespace line that counts against the budget.
    """
    proc = notify(BLOCKED | {"IMPACT": "fine, serving fc67d3d8.\n", "ACTION": "fix pyasn1.\n"})

    assert proc.returncode == 0, proc.stderr
    assert body(proc) == [
        "⛔ DEPLOY BLOCKED — prod is 3 commits behind master",
        "Prod: fine, serving fc67d3d8.",
        "",
        "Cause: ci / security / pip-audit failed on d980793b",
        "        → https://example.test/runs/1",
        "Do: fix pyasn1.",
        "Clears when: master's quality-gate goes green.",
    ]


@pytest.mark.parametrize(
    ("state", "headline", "label"),
    [
        ("deploy_blocked", "⛔ DEPLOY BLOCKED — the subject", "Cause"),
        ("deploy_failed", "❌ DEPLOY FAILED — the subject", "Cause"),
        # CAUSE is the antecedent here, so a deploy's cause reads as what shipped.
        ("deploy_succeeded", "✅ DEPLOY SUCCEEDED — the subject", "Shipped"),
        ("recovered", "🟢 RECOVERED — the subject", "Cause"),
    ],
)
def test_every_state_renders_the_same_skeleton(state: str, headline: str, label: str) -> None:
    proc = notify(
        {
            "STATE": state,
            "SUBJECT": "the subject",
            "IMPACT": "the impact",
            "CAUSE": "the cause",
            "ACTION": "the action",
            "CLEARS_WHEN": "the clearing condition",
        }
    )

    assert proc.returncode == 0, proc.stderr
    lines = body(proc)
    assert lines[0] == headline
    assert lines[1] == "Prod: the impact"
    assert f"{label}: the cause" in lines
    assert "Do: the action" in lines
    assert "Clears when: the clearing condition" in lines
    assert content_lines(lines) <= 8


def test_a_message_past_eight_content_lines_fails_instead_of_sending() -> None:
    proc = notify(
        BLOCKED
        | {
            "IMPACT": "\n".join(f"impact {n}" for n in range(5)),
            "CAUSE": "one\ntwo",
        }
    )

    assert proc.returncode != 0
    assert "::error::" in proc.stderr
    assert "max 8" in proc.stderr
    # The message is printed before refusing, so the run log still carries it.
    assert "impact 4" in proc.stdout


def test_a_state_missing_a_field_it_needs_fails_loudly() -> None:
    proc = notify({key: value for key, value in BLOCKED.items() if key != "CLEARS_WHEN"})

    assert proc.returncode != 0
    assert "CLEARS_WHEN is required for STATE=deploy_blocked" in proc.stderr


def test_an_unknown_state_fails_loudly() -> None:
    proc = notify(BLOCKED | {"STATE": "deploy_exploded"})

    assert proc.returncode != 0
    assert "unknown STATE 'deploy_exploded'" in proc.stderr


def test_a_free_text_message_still_renders_and_gets_the_run_link() -> None:
    proc = notify(
        {
            "MESSAGE": "**Backend Rollback Failed**\nThe rollback job failed.",
            "COLOR": "#ff6b6b",
            "GITHUB_RUN_ID": "42",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "theexperiencecompany/gaia",
        }
    )

    assert proc.returncode == 0, proc.stderr
    assert body(proc) == [
        "**Backend Rollback Failed**",
        "The rollback job failed.",
        "https://github.com/theexperiencecompany/gaia/actions/runs/42",
    ]


def check_runs(tmp_path: Path, runs: list[dict[str, str]], *, fail: bool = False) -> Path:
    """Stub `gh api` with a check-runs payload; --jq runs for real against it."""
    payload = tmp_path / "check-runs.json"
    payload.write_text(json.dumps({"check_runs": runs}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if [[ "{1 if fail else ""}" == "1" ]]; then echo "gh: HTTP 403 Forbidden" >&2; exit 1; fi
            filter=""
            while [[ $# -gt 0 ]]; do
              case "$1" in
                --jq) filter="$2"; shift ;;
              esac
              shift
            done
            jq -r "${{filter:-.}}" < "{payload}"
            """
        )
    )
    gh.chmod(0o755)
    return bin_dir


def check(name: str, conclusion: str, url: str) -> dict[str, str]:
    return {"name": name, "conclusion": conclusion, "html_url": url}


def test_failing_checks_names_each_failure_with_its_url(tmp_path: Path) -> None:
    bin_dir = check_runs(
        tmp_path,
        [
            check("ci / security / pip-audit", "failure", "https://example.test/runs/1"),
            check("ci / tests / pytest", "timed_out", "https://example.test/runs/2"),
            check("ci / lint / ruff", "success", "https://example.test/runs/3"),
            check("ci / docs / links", "skipped", "https://example.test/runs/4"),
        ],
    )

    proc = run("failing-checks", {"GITHUB_REPOSITORY": "o/r"}, SHA, bin_dir=bin_dir)

    assert proc.returncode == 0, proc.stderr
    # A green or skipped check is not a cause.
    assert proc.stdout.splitlines() == [
        "ci / security / pip-audit failed on d980793b",
        "→ https://example.test/runs/1",
        "ci / tests / pytest failed on d980793b",
        "→ https://example.test/runs/2",
    ]


def test_failing_checks_collapses_what_does_not_fit_into_a_count(tmp_path: Path) -> None:
    bin_dir = check_runs(
        tmp_path,
        [check(f"ci / lane {n}", "failure", f"https://example.test/runs/{n}") for n in range(3)],
    )

    proc = run("failing-checks", {"GITHUB_REPOSITORY": "o/r"}, SHA, "1", bin_dir=bin_dir)

    assert proc.stdout.splitlines() == [
        "ci / lane 0 failed on d980793b (+2 more)",
        "→ https://example.test/runs/0",
    ]


def test_failing_checks_says_so_when_nothing_failed(tmp_path: Path) -> None:
    bin_dir = check_runs(tmp_path, [check("ci / lint / ruff", "success", "https://e.test/3")])

    proc = run("failing-checks", {"GITHUB_REPOSITORY": "o/r"}, SHA, bin_dir=bin_dir)

    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["no failing check-runs reported on d980793b"]


def test_failing_checks_fails_when_the_request_does(tmp_path: Path) -> None:
    bin_dir = check_runs(tmp_path, [], fail=True)

    proc = run("failing-checks", {"GITHUB_REPOSITORY": "o/r"}, SHA, bin_dir=bin_dir)

    assert proc.returncode != 0
    assert "the cause is unknown, not absent" in proc.stderr


def test_the_notify_test_job_renders_every_state() -> None:
    """A state nothing renders is a template nobody would notice breaking."""
    document = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        step
        for step in document["jobs"]["notify-test"]["steps"]
        if (step.get("env") or {}).get("DRY_RUN") == "true"
    )

    for state in STATES:
        assert f"render {state} " in step["run"]
