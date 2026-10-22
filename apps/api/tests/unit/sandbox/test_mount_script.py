"""mount_juicefs.sh must cost the same on every mount, however much the workspace holds.

On JuiceFS every ownership or mode change is a metadata-engine round trip
(0.7s per file against hosted metadata, measured on E2B), so a recursive
chown/chmod under /workspace makes each sandbox create slower as the user's
files pile up: 40s for 31 files in .gaia, minutes for a whole workspace.
"""

from __future__ import annotations

import re

import pytest

from app.services.sandbox.lifecycle import MOUNT_SCRIPT_FILE

RECURSIVE_PERMISSION_CHANGE = re.compile(r"^\s*ch(own|mod)\s+(-\w*R\w*\s|--recursive)")


@pytest.mark.regression
def test_mount_script_never_changes_ownership_or_mode_recursively() -> None:
    offending = [
        line.strip()
        for line in MOUNT_SCRIPT_FILE.read_text().splitlines()
        if RECURSIVE_PERMISSION_CHANGE.match(line)
    ]
    assert offending == []
