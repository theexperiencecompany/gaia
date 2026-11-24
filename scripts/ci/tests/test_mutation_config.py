"""configure_mutmut is the one owner of mutmut's settings (scripts/ci/mutation.py)."""

from __future__ import annotations

from pathlib import Path
import tomllib

import mutation
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REQUEST = mutation.ModuleRequest(
    module="app/services/x.py", testfiles=("tests/unit/services/test_x.py",), ranges="[[1,2]]"
)


@pytest.mark.parametrize(
    "pyproject",
    [
        '[project]\nname = "api"\n',
        '[project]\nname = "api"\n\n[tool.mutmut]\nsource_paths = ["app"]\n\n[tool.ruff]\nx = 1\n',
    ],
    ids=["no-section", "stale-section"],
)
def test_the_workdir_gets_the_lanes_settings_whatever_the_checkout_has(
    tmp_path: Path, pyproject: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(pyproject)

    mutation.configure_mutmut(REQUEST, tmp_path)

    config = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert config["tool"]["mutmut"]["source_paths"] == ["app/services/x.py"]
    assert config["tool"]["mutmut"]["pytest_add_cli_args_test_selection"] == list(REQUEST.testfiles)
    assert config["project"]["name"] == "api"
    assert config["tool"].get("ruff", {"x": 1}) == {"x": 1}


def test_the_api_pyproject_carries_no_second_copy_of_the_settings() -> None:
    config = tomllib.loads((REPO_ROOT / "apps/api/pyproject.toml").read_text())
    assert "mutmut" not in config.get("tool", {})
