"""The pin-skew guard must pass on the real tree and fail on drift.

The fixture-based tests point the module's path constants at tmp files via
monkeypatch (``PRE_COMMIT`` / ``CODE_QUALITY`` / ``MAIN``), then drive
``main()`` end to end: consistent pins return rc 0, and a pin deleted from
its invocation but still mentioned in a comment returns rc 1 naming the
tool. A mention in a comment is prose, not a pin — it can never satisfy the
guard.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_tool_pins
import pytest

PRE_COMMIT_YAML = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.14.13
    hooks:
      - id: ruff
  - repo: local
    hooks:
      - id: bandit
        entry: bash -c "uvx --no-build bandit@1.9.4 -r app"
      - id: pip-audit
        entry: bash -c "uv export --frozen | uvx --no-build pip-audit@2.10.1"
      - id: gaia-mypy
        entry: bash -c 'uvx --no-build mypy@1.19.1 "$@"' --
"""

CODE_QUALITY_YML = """\
jobs:
  python-ruff:
    steps:
      - name: Ruff lint
        run: |
          uvx --no-build ruff@0.14.13 check .
  python-interrogate:
    steps:
      - name: Docstring coverage
        run: |
          uvx interrogate==1.7.0 -c pyproject.toml apps/api
  python-xenon:
    steps:
      - name: Complexity scan
        run: |
          uvx xenon==0.9.3 --max-absolute F apps/api
"""

MAIN_YML = """\
jobs:
  test-python:
    steps:
      - name: Diff coverage gate
        run: |
          uv tool run 'diff-cover==10.5.1' coverage.xml --fail-under=90
"""


@pytest.fixture
def pinned_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Fixture surfaces carrying every EXPECTED pin, as module constants."""
    files = {
        "PRE_COMMIT": tmp_path / "pre-commit-config.yaml",
        "CODE_QUALITY": tmp_path / "code-quality.yml",
        "MAIN": tmp_path / "main.yml",
    }
    files["PRE_COMMIT"].write_text(PRE_COMMIT_YAML, encoding="utf-8")
    files["CODE_QUALITY"].write_text(CODE_QUALITY_YML, encoding="utf-8")
    files["MAIN"].write_text(MAIN_YML, encoding="utf-8")
    for name, path in files.items():
        monkeypatch.setattr(check_tool_pins, name, path)
    return files


def _run(capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = check_tool_pins.main([])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_real_tree_is_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["python3", "tools/lints/check_tool_pins.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_consistent_pins_return_0(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    # The patched files must be what the guard read — without this, a broken
    # monkeypatch would silently pass against the real tree instead.
    assert all(path.exists() for path in pinned_surfaces.values())
    rc, out, err = _run(capsys)
    assert rc == 0, err
    assert "OK" in out


def test_deleted_pin_mentioned_in_comment_fails(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The real pin is gone; only the comment still names it.

    The old whole-file substring search was satisfied by that comment alone —
    this is the spoof that must fail.
    """
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace(
            "uvx --no-build ruff@0.14.13 check .",
            "          # uvx --no-build ruff@0.14.13 check .",
        ),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 1
    assert "ruff is not pinned to 0.14.13" in err
    assert "code-quality.yml" in err
    assert "1 unpinned tool invocation" in err


@pytest.mark.parametrize(
    "run_block",
    [
        # A full-line comment names the pin; the invocation itself is unpinned.
        "          # ruff@0.14.13\n          uvx --no-build ruff check .",
        # The only mention rides a trailing comment on an unpinned invocation.
        "          uvx --no-build ruff check .  # ruff@0.14.13",
    ],
)
def test_comment_only_mention_never_satisfies(
    pinned_surfaces: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    run_block: str,
) -> None:
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace("          uvx --no-build ruff@0.14.13 check .", run_block),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 1
    assert "ruff is not pinned to 0.14.13" in err


def test_real_pin_with_trailing_comment_still_counts(
    pinned_surfaces: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Cutting each line at its first ``#`` must not discard a genuine pin."""
    pinned_surfaces["CODE_QUALITY"].write_text(
        CODE_QUALITY_YML.replace(
            "uvx --no-build ruff@0.14.13 check .",
            "uvx --no-build ruff@0.14.13 check .  # pinned — bump with EXPECTED",
        ),
        encoding="utf-8",
    )
    rc, out, err = _run(capsys)
    assert rc == 0, err
