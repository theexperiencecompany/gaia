"""The zero-reference check is the half vulture's enforced set cannot see.

An unused module constant is invisible to the dead-code gate (it drops
"unused variable" findings), and vulture's name matching can hide a name that
collides elsewhere. This check only reports a top-level name that appears
nowhere but its own definition, so it has no false positives to allowlist.
"""

from pathlib import Path

import dead_symbols
import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    app = tmp_path / "apps" / "api" / "app"
    app.mkdir(parents=True)
    (app / "used.py").write_text('DEAD = "dead"\nLIVE = "live"\n')
    (app / "consumer.py").write_text("from app.used import LIVE\n")
    (app / "dead.py").write_text('FORGOTTEN = "nobody reads this"\n')
    return tmp_path


def test_reports_a_name_nothing_references(repo: Path) -> None:
    findings = dead_symbols.zero_ref_symbols(repo / "apps/api/app", repo)

    assert [(name, line) for _, name, line in findings] == [
        ("FORGOTTEN", 1),
        ("DEAD", 1),
    ]


def test_a_name_used_in_its_own_module_is_live(repo: Path) -> None:
    names = {name for _, name, _ in dead_symbols.zero_ref_symbols(repo / "apps/api/app", repo)}

    assert "LIVE" not in names


def test_a_reference_in_a_sibling_module_is_live(repo: Path) -> None:
    names = {name for _, name, _ in dead_symbols.zero_ref_symbols(repo / "apps/api/app", repo)}

    assert "LIVE" not in names
