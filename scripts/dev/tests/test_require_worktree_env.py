"""A linked worktree's dev process refuses to start on the main checkout's ports and database."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "require-worktree-env.sh"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def checkouts(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
        cwd=main,
    )
    linked = tmp_path / "linked"
    _git("worktree", "add", "-q", "--detach", str(linked), cwd=main)
    return main, linked


def _check(cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k != "GAIA_WT_SLOT"}
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=cwd,
        env={**clean, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_main_checkout_needs_no_worktree_env(checkouts: tuple[Path, Path]) -> None:
    main, _ = checkouts
    assert _check(main).returncode == 0


def test_a_linked_worktree_without_the_file_is_told_to_create_it(
    checkouts: tuple[Path, Path],
) -> None:
    _, linked = checkouts
    result = _check(linked)
    assert result.returncode == 1
    assert "mise run wt:env" in result.stderr


def test_a_file_nobody_loaded_is_refused(checkouts: tuple[Path, Path]) -> None:
    _, linked = checkouts
    (linked / ".env.worktree").write_text("GAIA_WT_SLOT=7\n")
    result = _check(linked)
    assert result.returncode == 1
    assert "not loaded" in result.stderr


def test_another_checkouts_env_is_refused(checkouts: tuple[Path, Path]) -> None:
    _, linked = checkouts
    (linked / ".env.worktree").write_text("GAIA_WT_SLOT=7\n")
    assert _check(linked, GAIA_WT_SLOT="9").returncode == 1


def test_the_loaded_file_passes(checkouts: tuple[Path, Path]) -> None:
    _, linked = checkouts
    (linked / ".env.worktree").write_text("GAIA_WT_SLOT=7\n")
    assert _check(linked, GAIA_WT_SLOT="7").returncode == 0
