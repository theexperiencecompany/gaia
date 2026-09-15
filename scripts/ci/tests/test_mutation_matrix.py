"""Unit tests for the mutation-matrix detector (scripts/ci/lib/mutation_matrix.py).

The detector's reference logic is what decides whether a changed module has
tests — a silent regression here would let the mutation lane skip modules
it should check. These tests pin the AST-based detection against fixture
trees so the logic is proven without running mutmut.
"""

import importlib.util
import io
import json
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


def test_the_contract_tier_is_kept_beside_unit_and_the_slow_tiers_still_drop(
    tmp_path: Path,
) -> None:
    # Contracts are the only tier that runs a repository's queries against real
    # Mongo, and they cost ~2s — dropping them with e2e is how every changed
    # repository method read as "no covering test" while the gate passed.
    hits = [
        "apps/api/tests/unit/db/repositories/test_users.py",
        "apps/api/tests/contracts/test_users_repository.py",
        "apps/api/tests/e2e/test_onboarding_flow.py",
        "apps/api/tests/integration/real/test_users_real.py",
    ]

    assert mm.with_unit_mirror("db/repositories/users", hits, tmp_path) == [
        "tests/unit/db/repositories/test_users.py",
        "tests/contracts/test_users_repository.py",
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


# ---------------------------------------------------------------------------
# The base the matrix scoped to — printed, because it decides everything else.
#
# PR #1202's plan job packed 119 modules into 6 shards for a diff of 11: the PR
# was still targeting master rather than the branch it was stacked on, so every
# module of the stack below it was re-mutated. Nothing in the lane's output
# named the base, so the only way to see it was to open a shard and recognise a
# module the PR never touched. The detector already resolves the base for its
# line ranges; it now says which one it used.
# ---------------------------------------------------------------------------

MATRIX_SCRIPT = REPO_ROOT / "scripts" / "ci" / "lib" / "mutation_matrix.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=GIT_ENV, capture_output=True)


def _rev(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, env=GIT_ENV).strip()


@pytest.fixture
def stacked_repo(tmp_path: Path) -> Path:
    """master, a branch stacked on it, and a feature branch stacked on THAT.

    The two candidate bases give different merge-bases on purpose: a detector
    that ignored GITHUB_BASE_REF and fell back to master would still print a
    plausible-looking sha, and only the value distinguishes the two.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    (root / "mod.py").write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "master")

    _git(root, "checkout", "-qb", "feat/base")
    (root / "mod.py").write_text("x = 2\n")
    _git(root, "commit", "-aqm", "the branch below")

    _git(root, "checkout", "-qb", "feat/stacked")
    (root / "mod.py").write_text("x = 3\n")
    _git(root, "commit", "-aqm", "the PR itself")
    return root


def _matrix_stderr(repo: Path, base_ref: str, **env: str) -> str:
    process = subprocess.run(
        ["python3", str(MATRIX_SCRIPT)],
        cwd=repo,
        input="",
        capture_output=True,
        text=True,
        check=False,
        env={**GIT_ENV, "GITHUB_BASE_REF": base_ref, **env},
    )
    assert process.returncode == 0, process.stderr
    return process.stderr


def test_the_matrix_names_the_base_it_scoped_to(stacked_repo: Path) -> None:
    stderr = _matrix_stderr(stacked_repo, "feat/base")

    assert "feat/base" in stderr


def test_the_matrix_prints_the_merge_base_it_actually_used(stacked_repo: Path) -> None:
    # The sha, not just the name: this is what makes a wrong base visible in
    # the log instead of only in a shard's module list an hour later.
    stacked = _rev(stacked_repo, "merge-base", "feat/base", "HEAD")
    against_master = _rev(stacked_repo, "merge-base", "master", "HEAD")

    stderr = _matrix_stderr(stacked_repo, "feat/base")

    assert stacked[:12] in stderr
    assert against_master[:12] not in stderr


def test_the_matrix_scopes_to_the_resolved_base_not_the_payload(
    stacked_repo: Path,
) -> None:
    """GAIA_PR_BASE wins over GITHUB_BASE_REF, and it has to.

    For a PR in a native GitHub stack the event payload names the stack's TRUNK
    in base.ref rather than the PR's parent (measured 2026-09-11 on #1175: the
    API said feat/first-steps-activation, every job's GITHUB_BASE_REF said
    master, and the plan took 119 modules for a one-module diff). `changes.sh
    base` resolves the parent from the API and the run exports it here.
    """
    # The payload says trunk, the resolver says parent.
    stderr = _matrix_stderr(stacked_repo, "master", GAIA_PR_BASE="feat/base")

    assert "feat/base" in stderr
    assert _rev(stacked_repo, "merge-base", "feat/base", "HEAD")[:12] in stderr
    assert _rev(stacked_repo, "merge-base", "master", "HEAD")[:12] not in stderr


# ---------------------------------------------------------------------------
# _changed_line_ranges — what the PR actually added, and nothing else.
#
# The ranges are the gate's whole scope: lib/mutation_gap.py demands a test for
# every line in them, and mutmut mutates only those lines. A range the PR did
# not touch is therefore a demand for a test of somebody else's code, reported
# against this PR. A pure deletion (`@@ -447 +446,0 @@`) used to produce one:
# the added-line count is explicitly 0, `max(count, 1)` read it as 1, and the
# range landed on whatever line followed the deletion. #1175 failed on exactly
# that — "conversation_service.py: 1 changed line no test reaches (line 446)"
# for a line no PR in the stack had changed.
# ---------------------------------------------------------------------------


def _ranges_for(
    repo: Path, monkeypatch: pytest.MonkeyPatch, before: str, after: str
) -> list[list[int]]:
    """Commit `before`, commit `after`, return the ranges of that real diff.

    A real repo and a real `git diff`, because the thing under test is how git's
    hunk header is read — a hand-written header would only test the fixture.
    """
    base_sha = _init_repo_with_commit(repo, before)
    (repo / "mod.py").write_text(after)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-qm", "change"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repo)
    return mm._changed_line_ranges("mod.py", base_sha)


def test_a_pure_deletion_contributes_no_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing was added, so there is nothing to mutate and nothing to demand a
    # test for. The line that moves up into the gap is not a changed line.
    ranges = _ranges_for(
        tmp_path,
        monkeypatch,
        "a = 1\nb = 2\nc = 3\nd = 4\n",
        "a = 1\nb = 2\nd = 4\n",
    )

    assert ranges == []


def test_a_one_line_change_is_its_own_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git writes `+N` with no count for a single line; that shorthand still
    # means one line, and dropping it would scope a real change to nothing.
    ranges = _ranges_for(
        tmp_path,
        monkeypatch,
        "a = 1\nb = 2\nc = 3\n",
        "a = 1\nb = 99\nc = 3\n",
    )

    assert ranges == [[2, 2]]


def test_a_multi_line_hunk_spans_exactly_its_added_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ranges = _ranges_for(
        tmp_path,
        monkeypatch,
        "a = 1\nz = 9\n",
        "a = 1\nb = 2\nc = 3\nd = 4\nz = 9\n",
    )

    assert ranges == [[2, 4]]


def test_a_deletion_beside_a_real_change_keeps_only_the_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The mixed case is the one that shipped: a PR that deletes in one place and
    # edits in another must be scoped to the edit alone.
    ranges = _ranges_for(
        tmp_path,
        monkeypatch,
        "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6\ng = 7\n",
        "a = 1\nc = 3\nd = 4\ne = 5\nf = 66\ng = 7\n",
    )

    assert ranges == [[5, 5]]


def test_a_deletion_only_module_is_dropped_from_the_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It has nothing to mutate, and passing it on would FAIL the shard.

    `mutation.sh module` refuses an empty line scope with exit 2 — deliberately,
    because an empty scope buckets every survivor as out-of-scope and exits 0.
    So the module has to be dropped by the planner rather than handed down, the
    same way a comment-only diff is.
    """
    app = tmp_path / "apps/api/app/services"
    app.mkdir(parents=True)
    (app / "thing.py").write_text("a = 1\nb = 2\nc = 3\n")
    tests = tmp_path / "apps/api/tests/unit/services"
    tests.mkdir(parents=True)
    (tests / "test_thing.py").write_text("import app.services.thing\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (app / "thing.py").write_text("a = 1\nc = 3\n")
    subprocess.run(
        ["git", "-c", "user.email=t@e.x", "-c", "user.name=t", "commit", "-aqm", "delete b"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD~1"], cwd=tmp_path, text=True
    ).strip()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mm, "_merge_base", lambda: base_sha)
    monkeypatch.setattr("sys.stdin", io.StringIO("apps/api/app/services/thing.py\n"))
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    assert mm.main() == 0
    assert json.loads(captured.getvalue()) == []
