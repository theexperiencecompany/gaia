"""Every builtin SKILL.md parses through the same parser the installer and GitHub discovery use."""

from pathlib import Path

import pytest

from app.agents.skills.parser import parse_skill_md
from app.agents.workspace.skill_loader import _BUILTIN_ROOT

BUILTIN_SKILL_FILES = sorted(_BUILTIN_ROOT.glob("*/SKILL.md"))


@pytest.mark.unit
def test_the_builtin_library_is_found() -> None:
    assert len(BUILTIN_SKILL_FILES) > 20


@pytest.mark.unit
@pytest.mark.parametrize("path", BUILTIN_SKILL_FILES, ids=lambda p: p.parent.name)
def test_a_builtin_skill_parses(path: Path) -> None:
    """An unquoted "description: X: Y" is invalid YAML, and the skill fails to install or validate."""
    metadata, body = parse_skill_md(path.read_text())

    assert metadata.description
    assert body
