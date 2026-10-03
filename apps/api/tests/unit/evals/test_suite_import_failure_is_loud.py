"""A suite that cannot import fails the eval CLI instead of vanishing from it.

The CLI loaded suites under suppress(ImportError), so when the browser suite's
import broke, --suite browser read as an unknown suite rather than a crash.
"""

from __future__ import annotations

from types import ModuleType

import pytest
from scripts.evals import __main__ as cli


def test_a_suite_that_cannot_import_fails_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_suite(name: str, package: str | None = None) -> ModuleType:
        raise ImportError(f"cannot import name 'read_cards' (while importing {name})")

    monkeypatch.setattr(cli, "load_opik_env", lambda: None)
    monkeypatch.setattr(cli, "import_module", import_suite)

    with pytest.raises(ImportError, match="read_cards"):
        cli._load_suites()
