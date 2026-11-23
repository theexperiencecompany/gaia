"""`sim-stack.sh up` publishes the database the API really uses, and fails when a process dies booting.

The API reads its database from MONGO_DB_NAME, not the URI's path, so the
fixtures' mongosh URI must name that database or they write where nothing reads.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "sim-stack.sh"
MONGO_DB = "mongodb://gaia:gaia@localhost:27018/gaia_test?authSource=admin"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


def _up(
    tmp_path: Path, *, process: str, db_name: str | None, curl: str = "exit 0"
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "mongosh", "echo 2.14.2")
    _stub(bin_dir, "curl", curl)
    # uv and pnpm start the stack's processes; each runs `process`.
    _stub(bin_dir, "uv", process)
    _stub(bin_dir, "pnpm", process)
    env = {k: v for k, v in os.environ.items() if k != "MONGO_DB_NAME"}
    env |= {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "OUT_DIR": str(tmp_path / "logs"),
        "GITHUB_ENV": str(tmp_path / "github_env"),
        "MONGO_DB": MONGO_DB,
        "BOOT_TIMEOUT_SECONDS": "5",
    }
    if db_name is not None:
        env["MONGO_DB_NAME"] = db_name
    return subprocess.run(
        ["bash", str(SCRIPT), "up"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    ("db_name", "expected"),
    [
        ("gaia_test_r3", "mongodb://gaia:gaia@localhost:27018/gaia_test_r3?authSource=admin"),
        (None, "mongodb://gaia:gaia@localhost:27018/GAIA?authSource=admin"),
    ],
)
def test_up_publishes_the_database_the_api_reads(
    tmp_path: Path, db_name: str | None, expected: str
) -> None:
    result = _up(tmp_path, process="exec sleep 2", db_name=db_name)
    assert result.returncode == 0, result.stderr
    published = (tmp_path / "github_env").read_text().splitlines()
    assert f"E2E_MONGO_URI={expected}" in published
    assert {"WEB_PORT=3000", "API_PORT=18400"} <= set(published)


def test_up_fails_when_a_process_exits_while_starting(tmp_path: Path) -> None:
    result = _up(tmp_path, process="exit 1", db_name=None, curl="exit 7")
    assert result.returncode != 0
    assert "llm-stub exited while starting" in result.stdout + result.stderr
    assert not (tmp_path / "github_env").exists()
