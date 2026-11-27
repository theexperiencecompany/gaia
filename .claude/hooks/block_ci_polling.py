"""PreToolUse hook: refuse Bash commands that wait on CI by hand or sleep in the foreground.

Polling is a loop that re-reads the same CI state over time: a `while`/`until`
around `gh`, a loop that sleeps, or a `for` whose `gh` call ignores its variable.
A `-c`/`-e` program or heredoc body given to a non-shell (python3, node) is not shell.
Reads the hook payload on stdin; exit 2 with a reason on stderr blocks the call.
"""

from __future__ import annotations

import json
from pathlib import PurePath
import re
import sys

MAX_FOREGROUND_SLEEP_S = 30
BLOCK_EXIT_CODE = 2

GH_POLL = re.compile(r"\bgh\s+(?:run\s+(?:list|view|watch)|pr\s+checks)\b")
GH_RUN_WATCH = re.compile(r"\bgh\s+run\s+watch\b")
WATCH_UTILITY = re.compile(r"(?:^|[;&|(\s])watch\s")
# `sleep` in command position: start of the line, or after an operator / do / then / else.
SLEEP = re.compile(r"(?:^|[;&|({\n]|\bdo|\bthen|\belse)\s*sleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
UNIT_SECONDS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
LOOP = re.compile(
    r"(?:^|[;&|(\s'\"])(?P<kind>while|until|for)\s+(?P<head>.*?)\bdo\b(?P<body>.*?)\bdone\b",
    re.DOTALL,
)
FOR_VARIABLE = re.compile(r"(\w+)\s+in\b")
READ_LOOP = re.compile(r"^\s*(?:IFS=\S*\s+)?read\b")
# A quoted program after -c / -e (python3 -c "…", bash -lc '…', node -e '…').
PROGRAM_ARG = re.compile(r"\s-[A-Za-z]*[ce]\s+(?P<q>['\"])(?P<body>.*?)(?<!\\)(?P=q)", re.DOTALL)
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
COMMAND_SEPARATOR = re.compile(r"[;&|()\n]")
# Commands whose -c argument or heredoc is itself shell code.
SHELL_RUNNERS = frozenset({"bash", "sh", "zsh", "dash", "ssh"})

WATCH_ADVICE = (
    "Wait on CI with `mise ci:watch <PR|branch>` (exits on the first red check that blocks merge and prints its failure; "
    "`mise ci:watch master` also watches the deploy, rollback included), "
    "run it in the background, and read the result when it exits."
)


def _runs_shell(prefix: str) -> bool:
    """Return whether the command that ``prefix`` ends inside is a shell."""
    words = [w for w in COMMAND_SEPARATOR.split(prefix)[-1].split() if "=" not in w]
    return bool(words) and PurePath(words[0]).name in SHELL_RUNNERS


def _drop_foreign_heredocs(command: str) -> str:
    lines = command.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for heredoc in HEREDOC.finditer(line):
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != heredoc.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            if _runs_shell(line[: heredoc.start()]):
                kept.extend(body)
    return "\n".join(kept)


def shell_code(command: str) -> str:
    """Return the command with every program a non-shell interpreter runs blanked out."""
    command = _drop_foreign_heredocs(command)
    return PROGRAM_ARG.sub(
        lambda m: m.group(0) if _runs_shell(command[: m.start()]) else " -c ''", command
    )


def longest_sleep_s(command: str) -> float:
    """Return the longest literal `sleep` duration in the command, 0 when there is none."""
    return max(
        (float(amount) * UNIT_SECONDS[unit] for amount, unit in SLEEP.findall(command)),
        default=0.0,
    )


def _loop_polls(kind: str, head: str, body: str) -> bool:
    if not GH_POLL.search(head + body):
        return False
    if SLEEP.search(body) or WATCH_UTILITY.search(body):
        return True
    if kind != "for":
        return not READ_LOOP.match(head)
    variable = FOR_VARIABLE.match(head)
    return variable is None or not re.search(rf"\$\{{?{variable.group(1)}\b", body)


def polls_ci(shell: str) -> bool:
    """Return whether the shell code re-reads CI state over time."""
    if not GH_POLL.search(shell):
        return False
    if WATCH_UTILITY.search(shell):
        return True
    return any(_loop_polls(m["kind"], m["head"], m["body"]) for m in LOOP.finditer(shell))


def block_reason(command: str, in_background: bool) -> str | None:
    """Return why the command must not run, or None when it may."""
    shell = shell_code(command)
    if GH_RUN_WATCH.search(shell):
        return f"`gh run watch` polls CI by hand. {WATCH_ADVICE}"
    if polls_ci(shell):
        return f"This loop polls CI with `gh` by hand. {WATCH_ADVICE}"
    slept = longest_sleep_s(shell)
    if not in_background and slept > MAX_FOREGROUND_SLEEP_S:
        return (
            f"A foreground `sleep` of {slept:g}s blocks the session "
            f"(limit {MAX_FOREGROUND_SLEEP_S}s). {WATCH_ADVICE} "
            "For anything else, start the command as a background run instead of sleeping."
        )
    return None


def main() -> int:
    """Read one PreToolUse payload from stdin; return 2 to block the Bash call, 0 to allow it."""
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
