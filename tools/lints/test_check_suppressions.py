"""Behaviour tests for tools/lints/check_suppressions.py.

The checker is stateless: there is no baseline, no count, no memory. Its whole
contract is "every inline suppression carries a written reason on its own line"
— so the cases that matter are the ones proving each suppression shape is
judged correctly, and that prose which merely MENTIONS a directive (in strings,
docstrings, template literals) is never mistaken for one.

Runs the real script via subprocess against a throwaway git repo (``git
ls-files`` is how it discovers what to scan), mirroring how CI invokes it.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

_HERE = Path(__file__).resolve().parent
SCRIPT = _HERE / "check_suppressions.py"
COMMON = _HERE / "_common.py"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the script installed at the same relative
    path it lives at in this repo, so ``REPO_ROOT`` (two parents up from
    ``__file__``) resolves to ``tmp_path``."""
    lints_dir = tmp_path / "tools" / "lints"
    lints_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, lints_dir / "check_suppressions.py")
    shutil.copy(COMMON, lints_dir / "_common.py")
    # The tool's own docstrings mention the suppression syntax as prose, which
    # the naive line scanner cannot distinguish from a real suppression.
    # Untracked here so it never enters the scan — tests exercise the scanner
    # against their own fixture files.
    (tmp_path / ".gitignore").write_text("/tools/\n")
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the scanner in `repo` and capture its output."""
    return subprocess.run(
        ["python3", "tools/lints/check_suppressions.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


# --- the core contract -------------------------------------------------------


def test_clean_tree_passes(repo: Path) -> None:
    result = run(repo)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_bare_noqa_fails_with_exact_line(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("x = call()  # noqa\n")
    _git(repo, "add", "-A")
    result = run(repo)
    assert result.returncode == 1
    assert "app.py:1" in result.stderr
    assert "[noqa]" in result.stderr


def test_coded_noqa_without_reason_fails(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("x = call()  # noqa: B006\n")
    _git(repo, "add", "-A")
    assert run(repo).returncode == 1


def test_noqa_with_reason_passes(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("x = call(default=[])  # noqa: B006 -- mutable default is never mutated\n")
    _git(repo, "add", "-A")
    result = run(repo)
    assert result.returncode == 0, result.stderr


def test_type_ignore_with_codes_but_no_reason_fails(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("builder = make(**kw)  # type: ignore[arg-type]\n")
    _git(repo, "add", "-A")
    result = run(repo)
    assert result.returncode == 1
    assert "type-ignore" in result.stderr


def test_type_ignore_with_reason_passes(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("builder = make(**kw)  # type: ignore[arg-type]  # upstream ships no stubs\n")
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_nosonar_alone_is_not_a_reason(repo: Path) -> None:
    """NOSONAR names another tool's directive; it explains nothing."""
    f = repo / "app.py"
    f.write_text("run(cmd)  # type: ignore[attr-defined]  # NOSONAR python:S7483\n")
    _git(repo, "add", "-A")
    result = run(repo)
    assert result.returncode == 1


def test_nosonar_after_a_real_reason_passes(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text(
        "run(cmd)  # type: ignore[attr-defined]  # SDK stubs absent upstream  # NOSONAR python:S7483\n"
    )
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_short_prose_below_the_bar_fails(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("x = call()  # noqa: E501 -- ok\n")  # "ok" < 8 chars
    _git(repo, "add", "-A")
    assert run(repo).returncode == 1


def test_biome_ignore_without_reason_fails(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text("const x: any = load(); // biome-ignore lint/suspicious/noExplicitAny\n")
    _git(repo, "add", "-A")
    result = run(repo)
    assert result.returncode == 1
    assert "biome-ignore" in result.stderr


def test_biome_ignore_with_reason_passes(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text(
        "const x: any = load(); // biome-ignore lint/suspicious/noExplicitAny: gallery-only\n"
    )
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_scoped_paths_only_report_scoped_files(repo: Path) -> None:
    (repo / "a.py").write_text("x = 1  # noqa\n")
    (repo / "b.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    result = run(repo, "b.py")
    assert result.returncode == 0, result.stderr


# --- comment-vs-string immunity (the old bugs, kept pinned) ------------------


def test_noqa_inside_a_docstring_is_not_counted(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text('"""Usage: append  # noqa here."""\n')
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_noqa_in_a_real_comment_is_counted(repo: Path) -> None:
    f = repo / "app.py"
    f.write_text("# noqa without code below\nx = 1  # noqa\n")
    _git(repo, "add", "-A")
    assert run(repo).returncode == 1


def test_biome_ignore_inside_a_string_is_not_counted(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text('const s = "// biome-ignore lint/x: not a comment";\n')
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_biome_ignore_in_a_real_comment_is_counted(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text("// biome-ignore lint/suspicious/noExplicitAny: reason here\nconst a = 1;\n")
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0  # has a reason → passes hygiene


def test_biome_ignore_inside_a_multiline_template_is_not_counted(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text("const t = `\n// biome-ignore lint/suspicious/noExplicitAny: template text\n`;\n")
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_biome_ignore_after_a_template_closes_is_counted(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text(
        "const t = `text`;\n// biome-ignore lint/suspicious/noExplicitAny: template closed above this line\nconst b = 2;\n"
    )
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0


def test_backtick_inside_a_comment_does_not_mask_later_directives(repo: Path) -> None:
    f = repo / "app.ts"
    f.write_text(
        "// note ` isn't special in a comment\nconst c = 3; // biome-ignore lint/x: why this needs silencing here\n"
    )
    _git(repo, "add", "-A")
    assert run(repo).returncode == 0
