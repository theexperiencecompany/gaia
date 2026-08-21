#!/usr/bin/env python3
"""Convert mypy/tsc/ruff/biome output to ::error file,line annotations."""

import re
import sys

patterns = [
    # mypy: path:line: error: msg  or path:line:col: error
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)?\s*(?:error|warning):"),
    # tsc: path(line,col): error TS...
    re.compile(r"^(?P<file>[^\(]+)\((?P<line>\d+),(?P<col>\d+)\):\s*error"),
    # ruff concise: path:line:col: CODE msg
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\d+:\s*[A-Z]+\d+\s"),
    # biome concise: path:line:col lint/category
    re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+)\s"),
]
for line in sys.stdin:
    for pat in patterns:
        m = pat.match(line.strip())
        if m:
            f = m.group("file").strip()
            line_no = m.group("line")
            # emit GitHub annotation
            print(f"::error file={f},line={line_no}::{line.strip()[:500]}")
            break
