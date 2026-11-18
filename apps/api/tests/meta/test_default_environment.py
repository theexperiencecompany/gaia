"""A plain uv sync or uv run in apps/api builds the environment CI tests the API in.

The API's runtime dependencies sit in the backend dependency group. When
the defaults left it out, uv run pytest built a venv where importing the
app failed on bson.
"""

from pathlib import Path
import subprocess

import pytest

API_DIR = Path(__file__).resolve().parents[2]


def _export(*groups: str) -> str:
    return subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-header", *groups],
        cwd=API_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.regression
def test_the_default_groups_are_the_ones_ci_installs() -> None:
    ci = _export("--no-default-groups", "--group", "backend", "--group", "dev")
    assert _export() == ci
