"""The dead-reference walk resolves the symbol, not the name.

A local variable named like a dead function used to make that function look
live; an import of the same name used to do the same. These cases pin the
difference between name matching and scope-aware resolution.
"""

from pathlib import Path

import dead_references
import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    app = tmp_path / "apps" / "api" / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "target.py").write_text("def target() -> None:\n    pass\n")
    (app / "consumer.py").write_text("import app.target as t\n\nt.target()\n")
    (app / "other.py").write_text("def target() -> None:\n    pass\n")
    tests = tmp_path / "apps" / "api" / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_other.py").write_text("from app.other import target\n")
    return tmp_path


def _verdicts(repo: Path) -> dict[tuple[str, str], str]:
    return {
        (definition.module, definition.name): verdict
        for definition, verdict in dead_references.audit(repo / "apps/api/app", repo)
    }


def test_an_attribute_chain_reaches_the_real_module(repo: Path) -> None:
    verdicts = _verdicts(repo)

    assert ("app.target", "target") not in verdicts
    assert verdicts[("app.other", "target")] == "TEST-ONLY"


def test_a_same_named_local_does_not_hide_dead_code(repo: Path) -> None:
    consumer = repo / "apps/api/app/consumer.py"
    consumer.write_text("def target() -> None:\n    pass\n\ntarget()\n")

    verdicts = _verdicts(repo)

    assert verdicts[("app.target", "target")] == "DEAD"
    assert verdicts[("app.other", "target")] == "TEST-ONLY"


def test_a_test_only_reference_is_not_production_use(repo: Path) -> None:
    verdicts = _verdicts(repo)

    assert verdicts[("app.other", "target")] == "TEST-ONLY"


def test_a_registered_route_is_live(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "api" / "app"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "routes.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
        "@router.get('/x')\ndef handler() -> None:\n    pass\n"
    )

    names = {definition.name for definition, _ in dead_references.audit(app, tmp_path)}

    assert "handler" not in names
