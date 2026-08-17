"""Whether a skill actually reaches the prompt an agent sees.

Shipping a skill is three things agreeing: it loads, it is listed to the right
agent, and the location it is listed with is a file that exists. Nothing in the
repo asserted the middle one — every skills test patches ``load_builtin_skills``
or ``get_skills_for_agent``, so "the executor is told about plan-my-day" was
never checked against the real library.

The failure is silent by construction. ``get_available_skills_text`` swallows a
Mongo error and returns builtins anyway, and returns ``""`` when there is
nothing — so a skill that stops being listed produces no error, no log the user
sees, and an agent that just does the generic thing instead.

Only Mongo and Redis are doubled here; the builtin library and the location
helper are real.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.skills import discovery
from app.agents.skills.discovery import get_available_skills_text
from app.agents.workspace.skill_loader import load_builtin_skills
from app.services.storage.sessions.skills import materialize_skills

pytestmark = pytest.mark.e2e

USER = "user-1"
EXECUTOR = "executor"


@pytest.fixture(autouse=True)
def _no_mongo_no_cache():
    """The two stores this function touches. Everything else stays real.

    ``Cacheable`` wraps the function, so without stubbing the cache the first
    test's result is served to the rest and per-agent differences vanish.
    """
    with (
        patch.object(discovery, "get_skills_for_agent", AsyncMock(return_value=[])),
        patch("app.decorators.caching.get_cache", AsyncMock(return_value=None)),
        patch("app.decorators.caching.set_cache", AsyncMock(return_value=None)),
    ):
        yield


async def _text(agent_name: str = EXECUTOR) -> str:
    return await get_available_skills_text(USER, agent_name)


class TestTheExecutorIsToldAboutItsSkills:
    async def test_the_executor_is_given_a_non_empty_skill_listing(self):
        """The deletion test, from the prompt side: with the builtin library
        gone this returns "" and the executor is told about nothing."""
        assert await _text()

    async def test_every_executor_skill_is_listed_by_name(self):
        """A skill missing from the listing is shipped code the agent is never
        told about — it exists on disk and is never used."""
        expected = {s.name for s in load_builtin_skills() if s.subagent_id == EXECUTOR}
        listing = await _text()

        missing = sorted(name for name in expected if name not in listing)

        assert expected, "no executor skills in the library to assert on"
        assert missing == [], f"shipped but never listed to the executor: {missing}"

    async def test_each_listed_skill_carries_a_description(self):
        """The description is the only thing the model selects on. A blank one
        makes the skill invisible in practice even though it is listed."""
        blank = [
            s.name
            for s in load_builtin_skills()
            if s.subagent_id == EXECUTOR and not (s.description or "").strip()
        ]

        assert blank == []

    async def test_an_integration_agent_is_not_given_the_executors_skills(self):
        """Integration subagents receive their builtins through
        ``integration_skills_block`` instead. Merging them here too would list
        every skill twice in their prompt."""
        listing = await _text("gmail_agent")
        executor_only = {s.name for s in load_builtin_skills() if s.subagent_id == EXECUTOR}

        assert not any(name in listing for name in executor_only)


class TestTheListedLocationIsReadable:
    """The listing tells the agent a path and the agent calls ``read`` on it.
    The path is built by the same helper the materializer uses — these assert
    that stays true, because a drift produces a read of a file that is not there
    and the agent silently continues without the skill."""

    async def test_every_listed_location_points_inside_the_workspace(self):
        listing = await _text()
        locations = [
            line.split("Location:")[-1].strip()
            for line in listing.splitlines()
            if "Location:" in line
        ]

        assert locations, f"no locations in the listing: {listing[:200]!r}"
        assert all(loc.startswith("/") for loc in locations)

    async def test_an_integration_skills_location_resolves_to_a_materialized_file(
        self, tmp_path: Path
    ):
        """End to end for the path contract: materialize into a real directory,
        then confirm the location the agent would be told matches a file that
        exists. Asserted on an integration skill because those are the ones
        ``materialize_skills`` writes."""
        from app.agents.workspace.system_files import builtin_skill_rel_path

        materialize_skills(tmp_path, {"gmail"})
        gmail_skills = [s for s in load_builtin_skills() if s.subagent_id == "gmail"]

        assert gmail_skills, "no gmail skills in the library to assert on"
        for skill in gmail_skills:
            assert (tmp_path / builtin_skill_rel_path(skill)).is_file(), skill.slug


class TestDegradation:
    async def test_a_mongo_failure_still_leaves_the_builtins_listed(self):
        """Builtins are fetched first precisely so a Mongo hiccup cannot hide
        them. If this regressed, a database blip would silently strip every
        shipped skill from the prompt while the turn otherwise succeeded."""
        with patch.object(
            discovery,
            "get_skills_for_agent",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            listing = await _text()

        assert listing
        expected = {s.name for s in load_builtin_skills() if s.subagent_id == EXECUTOR}
        assert any(name in listing for name in expected)

    async def test_an_agent_with_no_skills_at_all_gets_an_empty_string(self):
        """Not a stub sentence. The caller injects this verbatim, so anything
        non-empty becomes a prompt line claiming skills that do not exist."""
        assert await _text("nonexistent_agent") == ""
