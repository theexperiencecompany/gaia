"""The pin-skew guard must pass on the real tree and fail on drift."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_real_tree_is_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["python3", "tools/lints/check_tool_pins.py"],
        cwd=root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
