#!/usr/bin/env bash
#
# changed-py-source.sh — like `changed-files.sh py`, but drops the paths the
# Python tools exclude in a full scan (tests, scripts, migrations, …).
#
# Passing explicit files to interrogate/xenon/bandit bypasses their config
# excludes, so a changed test file gets scanned on a PR when a full scan would
# skip it. The exclude list is read from pyproject's [tool.interrogate].exclude
# so there is a single source of truth.
#
# Same output contract as changed-files.sh: "__FULL__", empty, or a file list.
set -euo pipefail

FILES=$(scripts/ci/changed-files.sh py)

if [[ "$FILES" == "__FULL__" || -z "$FILES" ]]; then
  printf '%s\n' "$FILES"
  exit 0
fi

# Program via -c so the file list can be piped on stdin. Each exclude glob
# reduces to a path segment (**/tests) or a basename (**/conftest.py).
printf '%s\n' "$FILES" | python3 -c '
import pathlib
import sys
import tomllib

patterns = tomllib.loads(pathlib.Path("pyproject.toml").read_text())[
    "tool"
]["interrogate"]["exclude"]

segments, basenames = set(), set()
for pat in patterns:
    core = pat.strip("/")
    if core.startswith("**/"):
        core = core[3:]
    if core.endswith("/**"):
        core = core[:-3]
    core = core.strip("/")
    if "/" in core or "*" in core:
        continue
    (basenames if core.endswith(".py") else segments).add(core)

for line in filter(None, sys.stdin.read().splitlines()):
    parts = line.split("/")
    if segments & set(parts) or parts[-1] in basenames:
        continue
    print(line)
'
