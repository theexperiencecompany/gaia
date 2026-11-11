"""The PreToolUse hook that refuses hand-written CI polling (.claude/hooks/block_ci_polling.py).

Each case runs the real script as Claude Code does: the hook payload on stdin,
exit 2 plus a stderr reason to block, exit 0 to allow.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "block_ci_polling.py"


def run_hook(command: str, *, background: bool = False, tool: str = "Bash") -> tuple[int, str]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command, "run_in_background": background},
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "gh run watch 123456",
        "gh run watch --exit-status",
        "while true; do gh pr checks 1361; sleep 20; done",
        "until gh run view 99 --json status -q .status | grep -q completed; do sleep 10; done",
        "for i in $(seq 1 50); do gh run list --branch feat/x; done",
        "watch -n 30 gh pr checks 1361",
        "sleep 60",
        "sleep 31",
        "sleep 2m && gh pr view 1",
        "make build; sleep 300; tail -5 log",
        "while :; do\n  sleep 45\ndone",
    ],
)
def test_hand_polling_and_long_sleeps_are_blocked_with_the_watch_advice(command: str) -> None:
    code, stderr = run_hook(command)
    assert code == 2
    assert "mise ci:watch <PR>" in stderr


@pytest.mark.parametrize(
    "command",
    [
        "gh pr checks 1361",
        "gh run view 99 --log-failed",
        "gh run list --limit 5",
        "sleep 30",
        "sleep 5; curl -s localhost:8000/health",
        "mise ci:watch 1361",
        "for f in a b; do git add $f; done",
        "git commit -m 'stop sleeping on CI'",
        "pytest tests/unit/test_sleep_backoff.py",
    ],
)
def test_one_shot_reads_short_sleeps_and_unrelated_loops_are_allowed(command: str) -> None:
    assert run_hook(command) == (0, "")


def test_a_long_sleep_is_allowed_in_a_background_run() -> None:
    assert run_hook("sleep 600; echo done", background=True) == (0, "")


def test_a_gh_poll_loop_is_blocked_even_in_a_background_run() -> None:
    code, _ = run_hook("while true; do gh pr checks 7; sleep 60; done", background=True)
    assert code == 2


def test_a_non_bash_tool_is_never_inspected() -> None:
    assert run_hook("sleep 999", tool="Read") == (0, "")
