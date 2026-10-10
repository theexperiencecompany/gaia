"""runner.sh select trust gates, exercised with stubbed GitHub event data.

The home box runs only code from organisation members. Every path here is
decided before the runners API is probed, so a bogus token keeps the script
offline: a gate that leaks would show up as an attempted probe (reason
``api-unavailable``), never as ``online-idle``.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import pytest

SCRIPT = Path(__file__).parent.parent / "runner.sh"
REPO = "theexperiencecompany/gaia"


def select(**env: str) -> dict[str, str]:
    base = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "GITHUB_OUTPUT": "/dev/stdout",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_TOKEN": "stub-token-never-valid",
        "PR_HEAD_REPO": REPO,
    }
    base.update(env)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "select"],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


@pytest.mark.parametrize(
    ("association", "reason"),
    [
        ("COLLABORATOR", "untrusted-author"),
        ("CONTRIBUTOR", "untrusted-author"),
        ("FIRST_TIME_CONTRIBUTOR", "untrusted-author"),
        ("FIRST_TIMER", "untrusted-author"),
        ("NONE", "untrusted-author"),
    ],
)
def test_non_member_pr_never_reaches_the_box(association: str, reason: str) -> None:
    out = select(PR_AUTHOR_ASSOCIATION=association)
    assert out["runner"] == '["ubuntu-latest"]'
    assert out["is_self_hosted"] == "false"
    assert out["reason"] == reason


def test_fork_pr_is_rejected_before_the_author_check() -> None:
    out = select(PR_HEAD_REPO="outsider/gaia", PR_AUTHOR_ASSOCIATION="MEMBER")
    assert out["runner"] == '["ubuntu-latest"]'
    assert out["reason"] == "fork"


@pytest.mark.parametrize("actor", ["dependabot[bot]", "github-actions[bot]", "renovate[bot]"])
def test_bot_actor_never_reaches_the_box(actor: str) -> None:
    out = select(PR_AUTHOR_ASSOCIATION="MEMBER", GITHUB_ACTOR=actor)
    assert out["runner"] == '["ubuntu-latest"]'
    assert out["reason"] == "bot-actor"


def test_forced_github_skips_the_probe() -> None:
    out = select(PR_AUTHOR_ASSOCIATION="OWNER", FORCE_GITHUB="true")
    assert out["runner"] == '["ubuntu-latest"]'
    assert out["reason"] == "forced-github"


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", ""])
def test_member_pr_and_push_reach_the_probe(association: str) -> None:
    # Members (and pushes, which carry no association) pass every gate and
    # reach the API probe; the stub token cannot list runners, so the only
    # outcome that proves the gates let them through is the probe's fallback.
    out = select(PR_AUTHOR_ASSOCIATION=association)
    assert out["reason"] == "api-unavailable"


def test_every_ci_script_path_in_the_workflows_resolves() -> None:
    """A `scripts/ci/<x>.sh` named anywhere in CI must be a file that exists.

    Consolidating the scripts turned paths into path-plus-subcommand, and one
    blanket rename put the subcommand inside the select-runner composite's
    ``SCRIPT=`` variable. ``[[ -f "$SCRIPT" ]]`` then failed, select-runner
    exited 127, and every lane in both workflows skipped behind it.
    """
    repo = SCRIPT.parent.parent.parent
    pattern = re.compile(r"scripts/ci/[A-Za-z0-9_./-]+\.sh")
    missing = []
    for path in [*sorted(repo.glob(".github/**/*.yml")), repo / "mise.toml"]:
        for ref in pattern.findall(path.read_text()):
            if not (repo / ref).is_file():
                missing.append(f"{path.relative_to(repo)} -> {ref}")
    assert not missing, missing


def test_the_select_runner_composite_passes_select_as_an_argument() -> None:
    action = (SCRIPT.parent.parent.parent / ".github/actions/select-runner/action.yml").read_text()
    assert 'SCRIPT="${{ github.action_path }}/../../../scripts/ci/runner.sh"' in action
    assert 'bash "$SCRIPT" select' in action
