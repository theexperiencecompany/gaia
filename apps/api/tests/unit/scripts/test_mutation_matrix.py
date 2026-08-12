"""Unit tests for the mutation-matrix detector (scripts/ci/mutation-matrix.py).

The detector's reference logic is what decides whether a changed module has
tests — a silent regression here would let the mutation lane skip modules
it should check. These tests pin the AST-based detection against fixture
trees so the logic is proven without running mutmut.
"""

import importlib.util
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
_SPEC = importlib.util.spec_from_file_location(
    "mutation_matrix", REPO_ROOT / "scripts" / "ci" / "mutation-matrix.py"
)
assert _SPEC is not None and _SPEC.loader is not None
mm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mm)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_module_refs_collect_import_forms(tmp_path: Path) -> None:
    test_file = tmp_path / "test_refs.py"
    _write(
        tmp_path,
        "test_refs.py",
        "import app.one\nfrom app.two import x\nfrom app.pkg import sub\n",
    )
    refs = mm._module_refs(test_file)

    assert "app.one" in refs
    assert "app.two" in refs
    assert "app.pkg" in refs
    assert "app.pkg.sub" in refs


def test_module_refs_collect_patch_target_strings(tmp_path: Path) -> None:
    test_file = tmp_path / "test_patch.py"
    _write(
        tmp_path,
        "test_patch.py",
        "from unittest.mock import patch\n"
        'patch("app.agents.tools.integrations.google_meet_tool")\n'
        'PREFIX = "app.services.foo"\n'
        'SHORT = "app.x"\n'
        'plain = "not a module"\n',
    )
    refs = mm._module_refs(test_file)

    assert "app.agents.tools.integrations.google_meet_tool" in refs
    assert "app.services." + "foo" in refs
    assert "app.x" in refs
    assert "not a module" not in refs


def test_module_refs_reject_embedded_module_strings(tmp_path: Path) -> None:
    """A module name embedded in fixture data (quotes/parens) is not a reference."""
    test_file = tmp_path / "test_embedded.py"
    _write(
        tmp_path,
        "test_embedded.py",
        "'patch(\"app.agents.tools.integrations.google_meet_tool\", ...)'\n"
        'assert "app.agents.tools.integrations." + "google_meet_tool" in refs\n',
    )
    refs = mm._module_refs(test_file)

    assert not any("google_meet" in ref for ref in refs)


def test_module_refs_find_fstring_patch_targets(tmp_path: Path) -> None:
    """f"{MODULE}.thing" patch targets still expose the bare module constant."""
    test_file = tmp_path / "test_fstring.py"
    _write(
        tmp_path,
        "test_fstring.py",
        'MODULE = "app.api.v1.endpoints.memory"\npatch(f"{MODULE}.memory_engine.list_memories")\n',
    )
    refs = mm._module_refs(test_file)

    assert "app.api.v1.endpoints.memory" in refs


def test_test_files_for_finds_importer(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/unit/tools/test_google_meet.py",
        "from app.agents.tools.integrations.google_meet_tool import register_google_meet_custom_tools\n",
    )
    _write(tmp_path, "tests/unit/other/test_unrelated.py", "from app.unrelated import thing\n")

    hits = mm._test_files_for("agents/tools/integrations/google_meet_tool", tmp_path)

    assert hits == [str(tmp_path / "tests/unit/tools/test_google_meet.py")]


def test_test_files_for_finds_patch_string(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/unit/api/test_conversations.py",
        "from unittest.mock import patch\n"
        'patch("app.api.v1.endpoints.conversations.get_conversations")\n',
    )

    hits = mm._test_files_for("api/v1/endpoints/conversations", tmp_path)

    assert hits == [str(tmp_path / "tests/unit/api/test_conversations.py")]


def test_tokens_without_comments_treats_trailing_and_whole_line_comments_as_inert() -> None:
    """A trailing `# noqa` and a whole-line comment both disappear from the
    token stream — the two shapes the suppression burn-down actually produced.
    """
    with_comments = mm._tokens_without_comments(
        "try:\n    pass\nexcept Exception as e:  # noqa: BLE001\n    pass\n# a whole line comment\ny = 2\n"
    )
    without_comments = mm._tokens_without_comments(
        "try:\n    pass\nexcept Exception as e:\n    pass\ny = 2\n"
    )

    assert with_comments == without_comments


def test_tokens_without_comments_still_distinguishes_real_code_changes() -> None:
    a = mm._tokens_without_comments("return 1  # noqa: E501\n")
    b = mm._tokens_without_comments("return 2\n")

    assert a != b


def test_tokens_without_comments_returns_none_on_syntax_error() -> None:
    assert mm._tokens_without_comments("def f(:\n") is None


def _init_repo_with_commit(root: Path, content: str) -> str:
    """A throwaway git repo with one file committed; returns that commit's sha."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    (root / "mod.py").write_text(content)
    subprocess.run(["git", "add", "mod.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_is_comment_only_change_true_when_only_a_trailing_noqa_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_sha = _init_repo_with_commit(
        tmp_path, "try:\n    pass\nexcept Exception as e:  # noqa: BLE001\n    pass\n"
    )
    (tmp_path / "mod.py").write_text("try:\n    pass\nexcept Exception as e:\n    pass\n")

    monkeypatch.chdir(tmp_path)

    assert mm._is_comment_only_change("mod.py", base_sha) is True


def test_is_comment_only_change_false_when_a_return_value_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_sha = _init_repo_with_commit(tmp_path, "def f():\n    return 1\n")
    (tmp_path / "mod.py").write_text("def f():\n    return 2\n")

    monkeypatch.chdir(tmp_path)

    assert mm._is_comment_only_change("mod.py", base_sha) is False


def test_is_comment_only_change_false_for_a_file_the_base_never_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "empty base", "--allow-empty"], cwd=tmp_path, check=True
    )
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n")

    monkeypatch.chdir(tmp_path)

    assert mm._is_comment_only_change("mod.py", base_sha) is False
