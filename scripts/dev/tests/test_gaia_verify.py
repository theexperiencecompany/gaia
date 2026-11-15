"""mise ci:local (scripts/dev/gaia_verify.py) when nx cannot answer."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]


def _checkout_without_node_modules(tmp_path: Path) -> Path:
    """Build a git checkout carrying ci:local and the nx lib it reads, and no node_modules."""
    root = tmp_path / "checkout"
    for rel in ("scripts/dev/gaia_verify.py", "scripts/ci/lib/nx_affected.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, root / rel)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


def test_ci_local_without_node_modules_names_the_install_command(tmp_path: Path) -> None:
    """Regression: a fresh worktree got a CalledProcessError traceback from `nx graph`."""
    root = _checkout_without_node_modules(tmp_path)

    process = subprocess.run(
        [sys.executable, str(root / "scripts" / "dev" / "gaia_verify.py"), "--list"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 2
    assert process.stderr.strip().splitlines() == [
        f"ci:local: node_modules is not installed in {root.resolve()}, so nx cannot run. "
        "Run: pnpm install --frozen-lockfile"
    ]
