"""The 37 shipped skills, against the real library and the real filesystem.

Every existing skills test patches load_builtin_skills, so today rm -rf
app/agents/skills/builtin/ would leave the whole suite green — nothing asserts
the library that actually ships; this file does not patch it.

A skill is only useful if two independently computed things agree: the prompt
path (system_files.builtin_skill_rel_path) and the materialized file path
(sessions.skills.materialize_skills). Nothing else checks they match — a
drift means the agent is told to read a file that isn't there, gets nothing,
and silently falls back to generic behaviour with no error anywhere. Nothing
here is patched except a temp directory; materialization is plain Path work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.workspace.skill_loader import load_builtin_skills, skills_by_subagent
from app.agents.workspace.system_files import builtin_skill_rel_path
from app.services.storage.sessions.skills import materialize_skills

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def library():
    """Load the real shipped library, unpatched on purpose — that is the whole test."""
    return load_builtin_skills()


class TestTheLibraryShips:
    def test_the_builtin_library_is_not_empty(self, library):
        """The deletion test: every other skills test patches load_builtin_skills, so only this one goes red if app/agents/skills/builtin/ is removed."""
        assert library, "no builtin skills loaded — the shipped library is missing or unparseable"

    def test_every_shipped_skill_parses(self, library):
        """A malformed SKILL.md is skipped rather than raising, so a broken frontmatter edit silently drops that skill — counting catches it."""
        on_disk = {
            path.parent.name for path in Path("app/agents/skills/builtin").glob("*/SKILL.md")
        }
        loaded = {skill.slug for skill in library}

        assert on_disk - loaded == set(), f"shipped but failed to parse: {on_disk - loaded}"

    def test_every_skill_declares_a_slug_and_a_target(self, library):
        """The slug is the write directory and the target is which agent is told — either missing makes the skill unreachable."""
        broken = [s for s in library if not s.slug or not getattr(s, "target", None)]

        assert broken == []

    def test_slugs_are_unique(self, library):
        """Materialization writes to skills/<slug>/ — two skills sharing a slug means one silently overwrites the other."""
        slugs = [s.slug for s in library]

        assert len(slugs) == len(set(slugs))

    def test_the_executor_and_the_provider_agents_both_have_skills(self, library):
        """Grouping drives who is told what — if every skill landed under one agent, the rest would be shipped code nobody hears about."""
        grouped = skills_by_subagent()

        assert grouped.get("executor")
        assert len([agent for agent, items in grouped.items() if items]) > 1


class TestPathContract:
    """The prompt says a path; materialization writes a file — nothing else checks they agree.

    Integration skills only: materialize_skills deliberately does NOT write
    executor bodies (they live in the /skills/<uid> overlay that
    link_system_files_into_workspace symlinks in), so asserting them here
    would be asserting against the design.
    """

    @staticmethod
    def _integration_skills(library):
        return [s for s in library if s.target and s.target != "executor"]

    def test_every_integration_skill_is_written_where_the_prompt_will_point(
        self, library, tmp_path: Path
    ):
        """The load-bearing test: a drift means the agent reads nothing and quietly falls back to generic behaviour with no error."""
        materialize_skills(tmp_path, set())

        missing = [
            (skill.slug, str(builtin_skill_rel_path(skill)))
            for skill in self._integration_skills(library)
            if not (tmp_path / builtin_skill_rel_path(skill)).is_file()
        ]

        assert missing == [], f"prompt path does not match what was written: {missing[:5]}"

    def test_an_executor_skill_is_addressed_under_the_plain_skills_directory(self, library):
        """Executor and integration skills use different layouts; swapping them points an agent at a subtree it never reads."""
        executor_skill = next(s for s in library if s.target == "executor")

        assert str(builtin_skill_rel_path(executor_skill)).startswith("skills/")

    def test_an_integration_skill_is_addressed_under_its_integration(self, library):
        integration_skill = self._integration_skills(library)[0]
        rel = str(builtin_skill_rel_path(integration_skill))

        assert rel.startswith("integrations/")
        assert "/agent/skills/" in rel

    def test_a_materialized_skill_file_has_content(self, library, tmp_path: Path):
        """An empty file satisfies "the path exists" and teaches the agent nothing."""
        materialize_skills(tmp_path, set())

        skill = self._integration_skills(library)[0]

        assert (tmp_path / builtin_skill_rel_path(skill)).read_text().strip()


class TestConnectedMarker:
    """Every integration's catalog is written regardless of connection.

    The .connected marker is what says which ones the user actually has —
    getting that backwards either hides skills the user can use or advertises
    tools they cannot.
    """

    def test_a_connected_integration_is_marked(self, tmp_path: Path):
        materialize_skills(tmp_path, {"gmail"})

        assert (tmp_path / "integrations" / "gmail" / "agent" / ".connected").is_file()

    def test_an_unconnected_integration_is_not_marked(self, tmp_path: Path):
        materialize_skills(tmp_path, {"gmail"})

        assert not (tmp_path / "integrations" / "googlecalendar" / "agent" / ".connected").exists()

    def test_disconnecting_clears_a_previously_set_marker(self, tmp_path: Path):
        """Re-materialization is how a disconnect takes effect — a stale marker keeps telling the agent it still has that integration."""
        materialize_skills(tmp_path, {"gmail"})
        materialize_skills(tmp_path, set())

        assert not (tmp_path / "integrations" / "gmail" / "agent" / ".connected").exists()

    def test_the_catalog_survives_disconnection(self, tmp_path: Path):
        """Only the marker moves — deleting the bodies on disconnect would mean reconnecting has to rewrite everything."""
        materialize_skills(tmp_path, {"gmail"})
        materialize_skills(tmp_path, set())

        assert list((tmp_path / "integrations" / "gmail" / "agent" / "skills").iterdir())
