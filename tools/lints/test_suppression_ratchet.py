"""Behaviour tests for scripts/ci/check-suppression-ratchet.sh.

The ratchet is a gate whose failure mode is silent: a broken ratchet passes
everything and nobody notices until suppressions have already accumulated. So
the cases that matter are the ones asserting it still says NO — a suite that
only checked the green paths would keep passing on a ratchet that never fails.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check-suppression-ratchet.sh"

# The fixtures embed real suppression syntax, so the ratchet counts this file's own
# test data as live suppressions — precisely the unavoidable case the marker exists
# for, and the first thing to dogfood it. Fixtures whose text already carries a
# valid `-- reason` are exempt on their own; only these two need the marker.
BARE = "x = 1  # noqa: E402\n"  # ratchet-allow -- fixture text, not a live suppression
NO_REASON = "x = 1  # noqa: E402  # ratchet-allow\n"  # ratchet-allow -- fixture text
EMPTY_REASON = "x = 1  # noqa: E402  # ratchet-allow --\n"
ALLOWED = "x = 1  # noqa: E402  # ratchet-allow -- bootstrap precedes imports\n"
ALLOWED_PLUS_BARE = "x = 1  # noqa: E402  # ratchet-allow -- ok\ny = 2  # noqa: F401\n"
TS_ALLOWED = "// biome-ignore lint: x  // ratchet-allow -- generated shim\nconst x = 1\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo with one clean baseline commit, and no suppressions."""
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "a.ts").write_text("const x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def run(repo: Path, py: str, ts: str = "const x = 1\n") -> subprocess.CompletedProcess[str]:
    """Commit the given file contents, then ratchet HEAD against the baseline."""
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "a.py").write_text(py)
    (repo / "a.ts").write_text(ts)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return subprocess.run(
        ["bash", str(SCRIPT), base], cwd=repo, capture_output=True, text=True, check=False
    )


def test_bare_suppression_fails(repo: Path) -> None:
    assert run(repo, BARE).returncode == 1


def test_allow_with_reason_passes(repo: Path) -> None:
    r = run(repo, ALLOWED)
    assert r.returncode == 0
    assert "1 ratchet-allow(s) across 1 changed file(s)" in r.stdout


def test_allow_without_reason_still_fails_and_warns(repo: Path) -> None:
    r = run(repo, NO_REASON)
    assert r.returncode == 1
    assert "ratchet-allow with no reason" in r.stderr


def test_allow_with_empty_reason_fails(repo: Path) -> None:
    assert run(repo, EMPTY_REASON).returncode == 1


def test_typescript_allow_with_reason_passes(repo: Path) -> None:
    r = run(
        repo,
        "x = 1\n",
        TS_ALLOWED,
    )
    assert r.returncode == 0


def test_allowed_line_does_not_mask_a_bare_one(repo: Path) -> None:
    """The allowance is line-scoped: it must not exempt the rest of the file."""
    r = run(repo, ALLOWED_PLUS_BARE)
    assert r.returncode == 1


def test_clean_tree_passes_without_allow_report(repo: Path) -> None:
    r = run(repo, "x = 2\n")
    assert r.returncode == 0
    assert "ratchet-allow(s) across" not in r.stdout
