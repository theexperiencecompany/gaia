"""The file-walking hygiene gates (scripts/ci/checks.mjs).

These gates decide what gets scanned, and getting that wrong is invisible: a
scan over zero files prints "✓ All files within size limits" and exits 0, which
reads exactly like a clean repo. That is the failure this file exists to catch —
the lane cannot tell you it checked nothing, so a test has to.

Driven as the real script against throwaway git repos: `checks.mjs` resolves its
file list with `git ls-files` relative to the working directory, so pointing it
at a sandbox repo scopes the whole gate without stubbing anything.
"""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKS = REPO_ROOT / "scripts" / "ci" / "checks.mjs"

# checks.mjs's own hard cap; a file past it must fail the gate outright.
HARD_LIMIT = 1200


def _repo(tmp_path: Path) -> Path:
    """A throwaway git repo — `git ls-files` is the gate's full-scan source."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _add(repo: Path, rel: str, lines: int) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"export const v{i} = {i};" for i in range(lines)))
    subprocess.run(["git", "add", rel], cwd=repo, check=True)


NODE = shutil.which("node")


def _run(repo: Path, *args: str, changed_files: str | None = None):
    # PATH inherited: node and git come from the mise-managed toolchain, not a
    # fixed system path. CHANGED_FILES is set explicitly per case so a value
    # leaking in from the surrounding lane cannot silently rescope the gate.
    env = {"PATH": os.environ["PATH"], "CHANGED_FILES": changed_files or ""}
    return subprocess.run(
        [NODE, str(CHECKS), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_the_full_scan_actually_scans(tmp_path: Path) -> None:
    """A full scan must look at the repo, not at an empty list.

    The regression: `explicitFileList()` read `process.argv` itself, so once the
    gates became subcommands of checks.mjs it picked up the subcommand NAME
    ("file-sizes") as an explicitly-scoped file. That list filtered to zero real
    paths, so every full scan took the explicit path over nothing and reported
    success — a green gate that had checked no files at all.
    """
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)

    process = _run(repo, "file-sizes")

    assert process.returncode == 1, f"gate passed over an oversized file\n{process.stdout}"
    assert "src/huge.ts" in process.stdout + process.stderr


def test_a_flag_does_not_switch_the_gate_to_explicit_mode(tmp_path: Path) -> None:
    # Same trap one step along: a bare `--quiet` must stay a flag. Counted as a
    # file it would filter to nothing and hand back the same vacuous green.
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)

    process = _run(repo, "file-sizes", "--quiet")

    assert process.returncode == 1, f"gate passed over an oversized file\n{process.stdout}"


def test_changed_files_still_scopes_the_scan(tmp_path: Path) -> None:
    # The other half of the contract: when a lane DOES name its files, the gate
    # must honour that and ignore everything else in the repo.
    repo = _repo(tmp_path)
    _add(repo, "src/huge.ts", HARD_LIMIT + 50)
    _add(repo, "src/small.ts", 10)

    process = _run(repo, "file-sizes", changed_files="src/small.ts")

    assert process.returncode == 0, process.stdout + process.stderr
    assert "src/huge.ts" not in process.stdout


def test_components_per_file_full_scan_reaches_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    components = "\n".join(f"export function Widget{i}() {{ return null; }}" for i in range(4))
    # One directory below the scanned root: the gate's full-scan pathspec is
    # `apps/web/src/**/*.tsx`, whose literal `/` after `**` needs a nested path.
    (repo / "apps/web/src/features").mkdir(parents=True)
    (repo / "apps/web/src/features/many.tsx").write_text(components)
    subprocess.run(["git", "add", "apps/web/src/features/many.tsx"], cwd=repo, check=True)

    process = _run(repo, "components-per-file")

    assert process.returncode == 1, f"gate passed over a 4-component file\n{process.stdout}"
    assert "apps/web/src/features/many.tsx" in process.stderr


def test_types_location_full_scan_reaches_the_repo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    types = "\n".join(f"export type T{i} = {{ a: number }};" for i in range(4))
    (repo / "apps/web/src").mkdir(parents=True)
    (repo / "apps/web/src/many.ts").write_text(types)
    subprocess.run(["git", "add", "apps/web/src/many.ts"], cwd=repo, check=True)

    process = _run(repo, "types-location", "--enforce")

    assert process.returncode == 1, f"gate passed over a 4-type file\n{process.stdout}"
    assert "apps/web/src/many.ts" in process.stdout


@pytest.mark.parametrize("sub", ["file-sizes", "components-per-file", "types-location"])
def test_an_unknown_subcommand_exits_two(tmp_path: Path, sub: str) -> None:
    # Guards the dispatch itself: a typo'd subcommand must be a hard error, not
    # a silent no-op that the lane would read as a pass.
    process = _run(_repo(tmp_path), f"{sub}-typo")

    assert process.returncode == 2
    assert "unknown subcommand" in process.stderr
