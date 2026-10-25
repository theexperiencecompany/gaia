"""PreToolUse hook: refuse Bash commands that wait on CI by hand or sleep in the foreground.

Reads the hook payload on stdin; exit 2 with a reason on stderr blocks the call.
"""

from __future__ import annotations

import json
import re
import sys

MAX_FOREGROUND_SLEEP_S = 30
BLOCK_EXIT_CODE = 2

GH_POLL = re.compile(r"\bgh\s+(?:run\s+(?:list|view|watch)|pr\s+checks)\b")
GH_RUN_WATCH = re.compile(r"\bgh\s+run\s+watch\b")
SHELL_LOOP = re.compile(r"(?:^|[;&|(\s])(?:while|until|for)\s")
WATCH_UTILITY = re.compile(r"(?:^|[;&|(\s])watch\s")
# `sleep` in command position: start of the line, or after an operator / do / then / else.
SLEEP = re.compile(r"(?:^|[;&|({\n]|\bdo|\bthen|\belse)\s*sleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}

WATCH_ADVICE = (
    "Wait on CI with `mise ci:watch <PR>` (exits on the first red lane and prints its failure), "
    "run it in the background, and read the result when it exits."
)


def longest_sleep_s(command: str) -> float:
    """Return the longest literal `sleep` duration in the command, 0 when there is none."""
    return max(
        (float(amount) * UNIT_SECONDS[unit] for amount, unit in SLEEP.findall(command)),
        default=0.0,
    )


def block_reason(command: str, in_background: bool) -> str | None:
    """Return why the command must not run, or None when it may."""
    if GH_RUN_WATCH.search(command):
        return f"`gh run watch` polls CI by hand. {WATCH_ADVICE}"
    if GH_POLL.search(command) and (SHELL_LOOP.search(command) or WATCH_UTILITY.search(command)):
        return f"This loop polls CI with `gh` by hand. {WATCH_ADVICE}"
    slept = longest_sleep_s(command)
    if not in_background and slept > MAX_FOREGROUND_SLEEP_S:
        return (
            f"A foreground `sleep` of {slept:g}s blocks the session "
            f"(limit {MAX_FOREGROUND_SLEEP_S}s). {WATCH_ADVICE} "
            "For anything else, start the command as a background run instead of sleeping."
        )
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return 0
    tool_input = payload.get("tool_input") or {}
    reason = block_reason(
        str(tool_input.get("command", "")), bool(tool_input.get("run_in_background"))
    )
    if reason is None:
        return 0
    sys.stderr.write(f"{reason}\n")
    return BLOCK_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
