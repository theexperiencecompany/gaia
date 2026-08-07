"""The 37 shipped skills, against the real library and the real filesystem.

The plan asks for a deletion test: remove the skills code and the skills tests
must fail. Today they would not. Every existing skills test patches
``load_builtin_skills``, so ``rm -rf app/agents/skills/builtin/`` leaves the
whole suite green — the library that ships in the product is asserted by
nothing.

That matters because a skill is only useful if two independent things agree: the
prompt tells the agent a path, and materialization wrote a file there. They are
computed in different modules (``system_files.builtin_skill_rel_path`` and
``sessions.skills.materialize_skills``) and nothing checks they match. When they
drift the agent is told to read a file that does not exist, gets nothing, and
silently does the generic thing instead — no error anywhere.

Nothing here is patched except a temp directory to write into. No mount needed:
materialization is plain ``Path`` work.
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
    """The real shipped library. Unpatched on purpose — that is the whole test."""
    return load_builtin_skills()


class TestTheLibraryShips:
    def test_the_builtin_library_is_not_empty(self, library):
        """The deletion test. Remove ``app/agents/skills/builtin/`` and
        ``load_builtin_skills`` returns an empty tuple — every other skills test
        in the repo stays green because they all patch this function, and this
        one goes red."""
        assert library, "no builtin skills loaded — the shipped library is missing or unparseable"

    def test_every_shipped_skill_parses(self, library):
        """A malformed SKILL.md is skipped at load time rather than raising, so
        a broken frontmatter edit removes that skill from the product silently.
        Counting is how that becomes visible."""
        on_disk = {
            path.parent.name for path in Path("app/agents/skills/builtin").glob("*/SKILL.md")
        }
        loaded = {skill.slug for skill in library}

        assert on_disk - loaded == set(), f"shipped but failed to parse: {on_disk - loaded}"

    def test_every_skill_declares_a_slug_and_a_target(self, library):
        """The slug is the directory name it is written to and the target is
        which agent is told about it. Either missing makes the skill unreachable."""
        broken = [s for s in library if not s.slug or not getattr(s, "target", None)]

        assert broken == []

    def test_slugs_are_unique(self, library):
        """Materialization writes to ``skills/<slug>/``; two skills sharing a
        slug means one silently overwrites the other on disk."""
        slugs = [s.slug for s in library]

        assert len(slugs) == len(set(slugs))

    def test_the_executor_and_the_provider_agents_both_have_skills(self, library):
        """Grouping drives who is told what. If every skill landed under one
        agent, the others would be shipped code nobody is ever told about."""
        grouped = skills_by_subagent()

        assert grouped.get("executor")
        assert len([agent for agent, items in grouped.items() if items]) > 1


class TestPathContract:
    """The prompt says a path; materialization writes a file. These are computed
    in two different modules and nothing else checks they agree.

    Integration skills only: ``materialize_skills`` deliberately does NOT write
    executor bodies (they live in the ``/skills/<uid>`` overlay that
    ``link_system_files_into_workspace`` symlinks in), so asserting them here
    would be asserting against the design.
    """

    @staticmethod
    def _integration_skills(library):
        return [s for s in library if s.target and s.target != "executor"]

    def test_every_integration_skill_is_written_where_the_prompt_will_point(
        self, library, tmp_path: Path
    ):
        """The load-bearing test. A drift means the agent is told to read a file
        that is not there, reads nothing, and quietly falls back to generic
        behaviour — a worse answer and no error anywhere."""
        materialize_skills(tmp_path, set())

        missing = [
            (skill.slug, str(builtin_skill_rel_path(skill)))
            for skill in self._integration_skills(library)
            if not (tmp_path / builtin_skill_rel_path(skill)).is_file()
        ]

        assert missing == [], f"prompt path does not match what was written: {missing[:5]}"

    def test_an_executor_skill_is_addressed_under_the_plain_skills_directory(self, library):
        """Executor and integration skills use different layouts; swapping them
        points an agent at a subtree it never reads."""
        executor_skill = next(s for s in library if s.target == "executor")

        assert str(builtin_skill_rel_path(executor_skill)).startswith("skills/")

    def test_an_integration_skill_is_addressed_under_its_integration(self, library):
        integration_skill = self._integration_skills(library)[0]
        rel = str(builtin_skill_rel_path(integration_skill))

        assert rel.startswith("integrations/")
        assert "/agent/skills/" in rel

    def test_a_materialized_skill_file_has_content(self, library, tmp_path: Path):
        """An empty file satisfies "the path exists" and teaches the agent
        nothing."""
        materialize_skills(tmp_path, set())

        skill = self._integration_skills(library)[0]

        assert (tmp_path / builtin_skill_rel_path(skill)).read_text().strip()


class TestConnectedMarker:
    """Every integration's catalog is written regardless of connection; the
    ``.connected`` marker is what says which ones the user actually has. Getting
    that backwards either hides skills the user can use or advertises tools they
    cannot."""

    def test_a_connected_integration_is_marked(self, tmp_path: Path):
        materialize_skills(tmp_path, {"gmail"})

        assert (tmp_path / "integrations" / "gmail" / "agent" / ".connected").is_file()

    def test_an_unconnected_integration_is_not_marked(self, tmp_path: Path):
        materialize_skills(tmp_path, {"gmail"})

        assert not (tmp_path / "integrations" / "googlecalendar" / "agent" / ".connected").exists()

    def test_disconnecting_clears_a_previously_set_marker(self, tmp_path: Path):
        """Re-materialization is how a disconnect takes effect. A marker left
        behind keeps telling the agent it still has that integration."""
        materialize_skills(tmp_path, {"gmail"})
        materialize_skills(tmp_path, set())

        assert not (tmp_path / "integrations" / "gmail" / "agent" / ".connected").exists()

    def test_the_catalog_survives_disconnection(self, tmp_path: Path):
        """Only the marker moves — deleting the bodies on disconnect would mean
        reconnecting has to rewrite everything."""
        materialize_skills(tmp_path, {"gmail"})
        materialize_skills(tmp_path, set())

        assert list((tmp_path / "integrations" / "gmail" / "agent" / "skills").iterdir())
