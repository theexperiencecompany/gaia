"""Behaviour tests for tools/lints/check_ignore_whys.py.

The checker replaces the set-ratchet: every escape hatch in the root
``pyproject.toml`` (ruff ``ignore``, ruff ``per-file-ignores``, weakening mypy
overrides) must carry a why-comment — trailing, or in a comment block directly
above (for override blocks: directly above the header, matching the repo's
convention of a rationale paragraph per block). Strict adjacency: a distant
comment must not silently cover a newly appended entry.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_ignore_whys.py"
COMMON = _HERE / "_common.py"

MINIMAL = """\
[tool.ruff.lint]
ignore = [
  "E741",  # ambiguous single-letter name is out of style scope
]

[tool.ruff.lint.per-file-ignores]
"apps/x/handlers.py" = ["ARG001"]  # DI binds by name; unused params are contract

[tool.mypy]
check_untyped_defs = true

# Legacy module: staged-strict migration pending, tracked by the island's growth.
[[tool.mypy.overrides]]
module = "legacy.*"
disallow_untyped_defs = false
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, lints_dir / "check_ignore_whys.py")
    shutil.copy(COMMON, lints_dir / "_common.py")
    (tmp_path / "pyproject.toml").write_text(MINIMAL)
    return tmp_path


def run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "tools/lints/check_ignore_whys.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_all_documented_passes(repo: Path) -> None:
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_undocumented_global_ignore_fails(repo: Path) -> None:
    text = MINIMAL.replace(
        '  "E741",  # ambiguous single-letter name is out of style scope',
        '  "E741",  # ambiguous single-letter name is out of style scope\n  "B007",',
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert 'ignore["B007"] has no why-comment' in result.stderr


def test_trailing_comment_stripped_from_global_ignore_fails(repo: Path) -> None:
    text = MINIMAL.replace(
        '  "E741",  # ambiguous single-letter name is out of style scope',
        '  "E741",',
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert 'ignore["E741"] has no why-comment' in result.stderr


def test_undocumented_per_file_entry_fails(repo: Path) -> None:
    text = MINIMAL.replace(
        "[tool.ruff.lint.per-file-ignores]\n",
        '[tool.ruff.lint.per-file-ignores]\n"apps/y/routes.py" = ["ARG002"]\n',
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert '"apps/y/routes.py"' in result.stderr


def test_weakening_mypy_override_without_comment_fails(repo: Path) -> None:
    text = MINIMAL.replace(
        "# Legacy module: staged-strict migration pending, tracked by the island's growth.\n",
        "",
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert "mypy-override[legacy.*]" in result.stderr


def test_tightening_override_is_not_an_escape_hatch(repo: Path) -> None:
    """A strict-island block (flags set true) needs no justification."""
    text = MINIMAL + (
        "\n[[tool.mypy.overrides]]\n"
        'module = "app.db.repositories.*"\n'
        "disallow_untyped_defs = true\n"
        "warn_return_any = true\n"
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 0, result.stderr


def test_multi_line_block_comment_counts(repo: Path) -> None:
    """Any prose line inside the contiguous block above the header documents it."""
    text = MINIMAL.replace(
        "# Legacy module: staged-strict migration pending, tracked by the island's growth.\n",
        "# Why legacy.* stays loose:\n"
        "# staged-strict migration pending, tracked by the island's growth.\n",
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 0, result.stderr


def test_distant_group_comment_does_not_cover_new_entry(repo: Path) -> None:
    """Strict adjacency: a comment above sibling A must not justify appended B."""
    text = MINIMAL.replace(
        '  "E741",  # ambiguous single-letter name is out of style scope',
        '  "E741",\n  "B007",  # unused loop variable renames are noisy churn',
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert 'ignore["E741"] has no why-comment' in result.stderr


def test_single_line_module_array_does_not_swallow_weakening_keys(repo: Path) -> None:
    """``module = ["x"]`` closes on its own line — every key after it is still a
    key, not another module name."""
    text = MINIMAL + ('\n[[tool.mypy.overrides]]\nmodule = ["vendor.sdk"]\nignore_errors = true\n')
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert "mypy-override[vendor.sdk] (ignore_errors)" in result.stderr


def test_warn_unused_ignores_false_is_a_weakening(repo: Path) -> None:
    """It defaults true; setting it false hides dead ``type: ignore`` comments."""
    text = MINIMAL + (
        '\n[[tool.mypy.overrides]]\nmodule = "flaky.*"\nwarn_unused_ignores = false\n'
    )
    (repo / "pyproject.toml").write_text(text)
    result = run(repo)
    assert result.returncode == 1
    assert "mypy-override[flaky.*] (warn_unused_ignores)" in result.stderr
