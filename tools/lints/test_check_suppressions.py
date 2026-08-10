"""Behaviour tests for tools/lints/check_suppressions.py.

The checker replaces a git-archaeology ratchet with a checked-in baseline, so
the cases that matter are the ones proving each of the old bugs is actually
fixed: a pure rename must not false-fail, a genuine new suppression must fail
with an exact file:line, and a baseline that has grown stale (more than the
tree now has) must fail too — the monotonic-shrink half of the contract.

Runs the real script via subprocess against a throwaway git repo (``git
ls-files`` is how it discovers what to scan), mirroring the sibling
``check_ignore_ratchet.py``'s dependence on a real ``pyproject.toml``.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_suppressions.py"
COMMON = _HERE / "_common.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the script installed at the same relative
    path it lives at in this repo, so ``REPO_ROOT`` (two parents up from
    ``__file__``) resolves to ``tmp_path``.
    """
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, lints_dir / "check_suppressions.py")
    shutil.copy(COMMON, lints_dir / "_common.py")
    # The tool's own docstrings mention the suppression syntax as prose, which
    # the naive line scanner cannot distinguish from a real suppression (same
    # limitation the old script had). Untracked here so it never enters the
    # scan — tests exercise the scanner against their own fixture files.
    (tmp_path / ".gitignore").write_text("/tools/\n")
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(repo: Path, message: str = "change") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the scanner in `repo` and capture its output."""
    return subprocess.run(
        ["python3", "tools/lints/check_suppressions.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_tree_passes(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1\n")
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    r = run(repo)
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_new_suppression_fails_with_correct_line(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    _commit(repo)
    assert run(repo, "--update").returncode == 0

    (repo / "a.py").write_text("x = 1\ny = 2  # noqa: E501\n")
    _commit(repo)
    r = run(repo)
    assert r.returncode == 1
    assert "a.py:2" in r.stderr
    assert "::error file=a.py,line=2::" in r.stdout


def test_stale_entry_fails(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1  # noqa: E501\n")
    _commit(repo)
    assert run(repo, "--update").returncode == 0

    baseline_path = repo / "config" / "suppressions-baseline.json"
    data = json.loads(baseline_path.read_text())
    data["entries"][0]["count"] += 1
    baseline_path.write_text(json.dumps(data, indent=2) + "\n")
    _commit(repo, "inflate baseline")

    r = run(repo)
    assert r.returncode == 1
    assert "stale baseline entry" in r.stderr
    assert "a.py" in r.stderr


def test_update_roundtrip(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1  # noqa: E501\n")
    (repo / "b.ts").write_text("// biome-ignore lint: x\nconst x = 1\n")
    _commit(repo)

    r = run(repo, "--update")
    assert r.returncode == 0
    baseline_path = repo / "config" / "suppressions-baseline.json"
    data = json.loads(baseline_path.read_text())
    kinds = {(e["path"], e["kind"]): e["count"] for e in data["entries"]}
    assert kinds == {("a.py", "noqa"): 1, ("b.ts", "biome-ignore"): 1}

    # Roundtrip: checking immediately after --update is clean.
    assert run(repo).returncode == 0


def test_renamed_file_passes_without_baseline_change(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1  # noqa: E501\ny = 2  # type: ignore\n")
    _commit(repo)
    assert run(repo, "--update").returncode == 0

    _git(repo, "mv", "a.py", "renamed.py")
    _commit(repo, "rename")

    r = run(repo)
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_renamed_and_edited_file_is_not_treated_as_a_free_rename(repo: Path) -> None:
    """A rename alone is free; a rename that also adds a suppression is not —
    content-hash matching only fires on byte-identical content."""
    (repo / "a.py").write_text("x = 1  # noqa: E501\n")
    _commit(repo)
    assert run(repo, "--update").returncode == 0

    _git(repo, "mv", "a.py", "renamed.py")
    (repo / "renamed.py").write_text("x = 1  # noqa: E501\ny = 2  # noqa: F401\n")
    _commit(repo, "rename and add a suppression")

    r = run(repo)
    assert r.returncode == 1
    assert "renamed.py" in r.stderr


def test_two_identical_files_do_not_collide_on_rename(repo: Path) -> None:
    """Two files with byte-identical content share a hash. If one baseline
    path vanishes, remapping it onto "the" current file with that hash would
    be a guess whenever more than one current file shares it — this must not
    happen; both are reported as new/stale instead of silently merged.
    """
    (repo / "a.py").write_text("x = 1  # noqa: E501\n")
    (repo / "b.py").write_text("x = 1  # noqa: E501\n")
    _commit(repo)
    assert run(repo, "--update").returncode == 0

    _git(repo, "mv", "a.py", "renamed.py")
    _commit(repo, "rename one of the two identical files")

    r = run(repo)
    assert r.returncode == 1
    assert "renamed.py" in r.stderr


def test_noqa_inside_a_docstring_is_not_counted(repo: Path) -> None:
    """The scanner's own module docstring documents `# noqa` as prose — a
    naive line scanner would count that as a real suppression. It must not.
    """
    (repo / "a.py").write_text('"""Docs mention # noqa here."""\nx = 1\n')
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "0 suppression" in r.stdout


def test_noqa_in_a_real_comment_is_counted(repo: Path) -> None:
    (repo / "a.py").write_text('"""Docs mention noqa in prose."""\nx = 1  # noqa: E501\n')
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "1 suppression" in r.stdout


def test_biome_ignore_inside_a_string_is_not_counted(repo: Path) -> None:
    (repo / "a.ts").write_text('const msg = "see // biome-ignore lint: x for docs";\n')
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "0 suppression" in r.stdout


def test_biome_ignore_in_a_real_comment_is_counted(repo: Path) -> None:
    (repo / "a.ts").write_text("// biome-ignore lint: x\nconst n = 1;\n")
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "1 suppression" in r.stdout


def test_biome_ignore_inside_a_multiline_template_is_not_counted(repo: Path) -> None:
    """The backtick-parity tracker must see the template body as string text."""
    (repo / "a.ts").write_text("const t = `\n// biome-ignore lint: x\n`;\nconst n = 1;\n")
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "0 suppression" in r.stdout


def test_biome_ignore_after_a_template_closes_is_counted(repo: Path) -> None:
    """Code after the closing backtick on the same line is code again."""
    (repo / "a.ts").write_text("const t = `\nbody\n`; // biome-ignore lint: x\n")
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "1 suppression" in r.stdout


def test_backtick_inside_a_comment_does_not_mask_later_directives(repo: Path) -> None:
    """A `` ` `` in an ordinary // comment must not toggle template state —
    otherwise every later directive in the file silently bypasses the check."""
    (repo / "a.ts").write_text(
        "// wrap it in `code` spans\nconst a = 1;\n// biome-ignore lint: x\n"
    )
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "1 suppression" in r.stdout


def test_directive_in_comment_on_template_close_line_is_counted(repo: Path) -> None:
    """The comment after a closing backtick on the same line is real code-side text."""
    (repo / "a.ts").write_text("const t = `\nbody\n`; // biome-ignore lint: x\n")
    _commit(repo)
    r = run(repo, "--update")
    assert r.returncode == 0
    assert "1 suppression" in r.stdout
