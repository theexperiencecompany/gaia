"""The full loop: the agent is told a path, and calling ``read`` on it works.

Everything else about skills is circumstantial until this holds. The listing can
name a skill, the materializer can write a file, and the agent can still get
nothing — because what the agent actually does is take the ``Location:`` string
out of its prompt and hand it verbatim to the ``read`` tool. Three components
have to agree on one string, and they are in three different modules.

This takes the location out of the real listing and feeds it to the real tool,
with no path construction of its own — constructing the path here would test
this file's idea of the path rather than the product's.

No mount is involved: ``read`` serves system-owned files (the builtin skills)
straight from process memory (``read_tool.py`` ``system_file_body``), which is
also why an agent can read them before any workspace provisioning has happened.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.skills import discovery
from app.agents.skills.discovery import get_available_skills_text
from app.agents.tools.coding.read_tool import read
from app.agents.workspace.skill_loader import load_builtin_skills

pytestmark = pytest.mark.e2e

USER = "user-1"
EXECUTOR = "executor"
CONFIG = {
    "configurable": {"user_id": USER, "thread_id": "conv-1"},
    "metadata": {"user_id": USER},
}

LOCATION = re.compile(r"Location:\s*(\S+)")


@pytest.fixture(autouse=True)
def _stores():
    """Mongo, Redis and the workspace-ownership probe.

    ``user_owns_regular_file`` decides whether a user's own copy shadows the
    system one; it is the only JuiceFS touch on this path and False is the
    honest answer for a user who has never overridden a builtin.
    """
    with (
        patch.object(discovery, "get_skills_for_agent", AsyncMock(return_value=[])),
        patch("app.decorators.caching.get_cache", AsyncMock(return_value=None)),
        patch("app.decorators.caching.set_cache", AsyncMock(return_value=None)),
        patch(
            "app.agents.tools.coding.read_tool.user_owns_regular_file",
            AsyncMock(return_value=False),
        ),
    ):
        yield


async def _locations() -> list[str]:
    """Exactly the paths the executor is told about, parsed from its prompt."""
    return LOCATION.findall(await get_available_skills_text(USER, EXECUTOR))


class TestTheAgentCanReadWhatItIsTold:
    async def test_the_listing_actually_contains_locations(self):
        """Guard for the two tests below: if the format changed and nothing
        parsed, they would vacuously pass over an empty list."""
        locations = await _locations()

        assert locations
        assert all(loc.startswith("/workspace/") for loc in locations)

    async def test_reading_a_listed_location_returns_that_skill(self):
        """The whole point. Take the first path the agent is given and call the
        real tool on it — no path construction here, because building the path
        in the test would only prove the test agrees with itself."""
        location = (await _locations())[0]

        result = await read.ainvoke({"path": location}, config=CONFIG)

        assert isinstance(result, str)
        assert not result.startswith("Error"), result
        assert result.strip()

    async def test_every_location_the_executor_is_given_is_readable(self):
        """One unreadable entry is a skill the agent is told it has and cannot
        use — and it fails silently, since ``read`` returns an error string the
        model simply reads and moves past."""
        unreadable = []
        for location in await _locations():
            result = await read.ainvoke({"path": location}, config=CONFIG)
            if not isinstance(result, str) or result.startswith("Error"):
                unreadable.append((location, str(result)[:80]))

        assert unreadable == [], f"listed but not readable: {unreadable}"

    async def test_the_content_read_back_is_the_shipped_skill_body(self):
        """Not just "some text at that path" — the actual skill. A path that
        resolved to the wrong file would satisfy every other assertion here."""
        listing = await get_available_skills_text(USER, EXECUTOR)
        first = LOCATION.search(listing)
        assert first is not None
        location = first.group(1)

        slug = location.rstrip("/").split("/")[-2]
        skill = next(s for s in load_builtin_skills() if s.slug == slug)

        result = await read.ainvoke({"path": location}, config=CONFIG)

        first_real_line = next(line.strip() for line in skill.body.splitlines() if line.strip())
        assert first_real_line in result


class TestFailureIsVisible:
    async def test_reading_a_path_that_does_not_exist_reports_an_error(self):
        """Control. Without it, a ``read`` that returned "" for everything would
        satisfy the tests above."""
        result = await read.ainvoke(
            {"path": "/workspace/skills/no-such-skill-xyz/skill.md"}, config=CONFIG
        )

        assert isinstance(result, str)
        assert "Error" in result or not result.strip()
