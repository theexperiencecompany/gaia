"""Unit tests for the mutation-matrix detector (scripts/ci/mutation-matrix.py).

The detector's reference logic is what decides whether a changed module has
tests — a silent regression here would let the mutation lane skip modules
it should check. These tests pin the AST-based detection against fixture
trees so the logic is proven without running mutmut.
"""

import importlib.util
from pathlib import Path

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
