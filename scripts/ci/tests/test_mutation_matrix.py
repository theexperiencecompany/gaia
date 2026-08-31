"""Unit tests for the mutation-matrix detector (scripts/ci/lib/mutation_matrix.py).

The detector's reference logic is what decides whether a changed module has
tests — a silent regression here would let the mutation lane skip modules
it should check. These tests pin the AST-based detection against fixture
trees so the logic is proven without running mutmut.
"""

import importlib.util
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "mutation_matrix", REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_matrix.py"
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


# ---------------------------------------------------------------------------
# with_unit_mirror — the gate mutates a module against EVERY referencing test
# file, not one.
#
# Picking one was the defect: a module whose tests span several files was
# measured against whichever the mirror-check or the sort happened to choose,
# and every mutant only the discarded files covered was reported as "no
# covering test" — informational, failing nothing. A module could pass the
# gate having killed nothing at all.
# ---------------------------------------------------------------------------


def test_every_referencing_file_is_kept_not_just_the_first(tmp_path: Path) -> None:
    hits = [
        "apps/api/tests/unit/agents/test_handoff_brief.py",
        "apps/api/tests/unit/tools/test_executor_tool.py",
    ]

    assert mm.with_unit_mirror("agents/tools/executor_tool", hits, tmp_path) == [
        "tests/unit/agents/test_handoff_brief.py",
        "tests/unit/tools/test_executor_tool.py",
    ]


def test_the_unit_mirror_leads_the_set_rather_than_replacing_it(tmp_path: Path) -> None:
    # The mirror used to short-circuit the scan entirely — it never even
    # computed the other hits. It is a member now, not an exit.
    _write(tmp_path, "tests/unit/services/test_cost_budget.py", "")
    hits = ["apps/api/tests/unit/middleware/test_accounting.py"]

    assert mm.with_unit_mirror("services/cost_budget", hits, tmp_path) == [
        "tests/unit/services/test_cost_budget.py",
        "tests/unit/middleware/test_accounting.py",
    ]


def test_the_mirror_is_not_duplicated_when_it_also_references_the_module(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/unit/services/test_cost_budget.py", "")
    hits = [
        "apps/api/tests/unit/services/test_cost_budget.py",
        "apps/api/tests/unit/middleware/test_accounting.py",
    ]

    assert mm.with_unit_mirror("services/cost_budget", hits, tmp_path) == [
        "tests/unit/services/test_cost_budget.py",
        "tests/unit/middleware/test_accounting.py",
    ]


def test_a_module_with_no_referencing_file_and_no_mirror_selects_nothing(
    tmp_path: Path,
) -> None:
    # Empty is what makes main() report "no test file anywhere" — the one
    # case that must still fail the lane loudly.
    assert mm.with_unit_mirror("services/orphan", [], tmp_path) == []


def test_a_mirror_alone_is_enough_when_nothing_references_the_module(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "tests/unit/services/test_orphan.py", "")

    assert mm.with_unit_mirror("services/orphan", [], tmp_path) == [
        "tests/unit/services/test_orphan.py"
    ]


def test_entries_carry_the_whole_list_under_a_plural_key() -> None:
    # Renamed from "testfile": a consumer still reading the old key now fails
    # with a KeyError instead of silently iterating a string's characters.
    entry = mm._entry("app/services/cost_budget.py", ["tests/unit/a.py", "tests/unit/b.py"], "")

    assert entry["testfiles"] == ["tests/unit/a.py", "tests/unit/b.py"]
    assert "testfile" not in entry


def test_a_test_file_is_parsed_once_no_matter_how_many_modules_are_planned(
    tmp_path: Path,
) -> None:
    """Reference detection must not re-parse the tree per changed module.

    Without memoization the scan is quadratic — every changed module re-parses
    every test file and, through the consumer fallback, every app file. On a
    whole-tree diff (429 modules) the plan step blew the lane's 10-minute
    ceiling and was cancelled, so nothing downstream got a gate at all. This
    asserts the parse count, which is the property that keeps it linear; a
    wall-clock assertion would be flaky on a loaded runner.
    """
    _write(tmp_path, "tests/unit/test_one.py", "import app.alpha\n")
    _write(tmp_path, "tests/unit/test_two.py", "import app.beta\n")
    mm._module_refs.cache_clear()
    mm._py_files.cache_clear()

    for module in ("alpha", "beta", "alpha", "beta"):
        mm._test_files_for(module, tmp_path)

    # Two files exist, so at most two parses no matter how many lookups ran.
    assert mm._module_refs.cache_info().currsize == 2
    assert mm._module_refs.cache_info().misses == 2
    assert mm._module_refs.cache_info().hits > 0


def test_module_refs_returns_an_immutable_set(tmp_path: Path) -> None:
    """Cached values are shared, so a caller must not be able to mutate one."""
    _write(tmp_path, "test_refs.py", "import app.one\n")

    refs = mm._module_refs(tmp_path / "test_refs.py")

    assert isinstance(refs, frozenset)
