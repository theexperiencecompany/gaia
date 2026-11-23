"""What the caller's shell already set wins over Infisical; Infisical fills only the gaps."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "infisical-run.sh"
# Stands in for `infisical run`: injects its secrets over the environment, then runs the command.
FAKE_INFISICAL = """#!/bin/sh
while [ "$1" != "--" ]; do shift; done
shift
export REDIS_URL=redis://shared-development:6379
export MONGO_DB_NAME=GAIA
export ONLY_IN_INFISICAL=from-the-vault
exec "$@"
"""


def _run(tmp_path: Path, caller_env: dict[str, str]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "infisical"
    fake.write_text(FAKE_INFISICAL)
    fake.chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **caller_env}
    printed = subprocess.run(
        ["bash", str(SCRIPT), "env"], env=env, check=True, capture_output=True, text=True
    ).stdout
    return dict(line.split("=", 1) for line in printed.splitlines() if "=" in line)


def test_a_value_the_caller_set_beats_the_vaults(tmp_path: Path) -> None:
    child = _run(tmp_path, {"REDIS_URL": "redis://localhost:6393/0", "MONGO_DB_NAME": "gaia_wt10"})
    assert child["REDIS_URL"] == "redis://localhost:6393/0"
    assert child["MONGO_DB_NAME"] == "gaia_wt10"


def test_a_value_only_the_vault_holds_still_arrives(tmp_path: Path) -> None:
    child = _run(tmp_path, {})
    assert child["ONLY_IN_INFISICAL"] == "from-the-vault"
    assert child["REDIS_URL"] == "redis://shared-development:6379"


def test_a_value_with_spaces_and_quotes_survives(tmp_path: Path) -> None:
    value = 'it\'s "quoted" $HOME and spaced'
    assert _run(tmp_path, {"REDIS_URL": value})["REDIS_URL"] == value
