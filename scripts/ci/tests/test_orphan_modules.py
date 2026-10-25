"""The orphan scan follows imports, not names.

A module that only a test imports is dead in production. Vulture cannot see
that (tests are excluded, and its analysis is name-based), so the reachability
walk is the gate: it must start from the real entrypoints, follow package
`__init__` re-exports, and report only what nothing reaches.
"""

from pathlib import Path

import orphan_modules
import pytest


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("")
    (app / "main.py").write_text("from app.used import thing\nfrom app.pkg import value\n")
    (app / "used.py").write_text("thing = 1\n")
    (app / "orphan.py").write_text("dead = 1\n")
    package = app / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .inner import value\n")
    (package / "inner.py").write_text("value = 1\n")
    return app


def test_reports_only_modules_no_entrypoint_reaches(app_dir: Path) -> None:
    orphans = orphan_modules.orphan_modules(app_dir)

    assert [module for _, module in orphans] == ["app.orphan"]


def test_a_package_init_reaches_its_relative_submodule(app_dir: Path) -> None:
    """`from .inner import value` is the common re-export shape; missing it would report live modules."""
    orphans = orphan_modules.orphan_modules(app_dir)

    assert "app.pkg.inner" not in {module for _, module in orphans}


def test_a_declared_dynamic_entrypoint_is_a_root(
    app_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(orphan_modules.DYNAMIC_MODULES, "app.orphan", "loaded by a CLI flag")

    assert orphan_modules.orphan_modules(app_dir) == []
