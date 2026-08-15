"""Unit tests for app.agents.skills.discovery.get_available_skills_text.

Mocks only get_skills_for_agent (the Mongo boundary) and load_builtin_skills
(process-memory but data-dependent) — the real merge/format/fallback logic
under test is untouched. @Cacheable wraps the real Redis client (already
running for this test tier); each test uses a unique user_id so cache entries
never collide across runs.
"""

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.agents.skills.discovery import get_available_skills_text
from app.agents.workspace.skill_loader import BuiltinSkill

_GET_SKILLS_FOR_AGENT = "app.agents.skills.discovery.get_skills_for_agent"
_LOAD_BUILTIN_SKILLS = "app.agents.skills.discovery.load_builtin_skills"


def _builtin(**overrides) -> BuiltinSkill:
    base: dict[str, Any] = {
        "slug": "test-skill",
        "name": "Test Skill",
        "description": "does a thing",
        "target": "executor",
        "subagent_id": "executor",
        "body": "# Test Skill\nDo the thing.",
    }
    base.update(overrides)
    return BuiltinSkill(**base)


class TestMongoFailureFallback:
    """The Mongo lookup failing must degrade to builtins-only text, not
    propagate and break prompt construction for every agent turn — but it
    must not disappear silently either."""

    async def test_mongo_failure_falls_back_to_builtins_only_and_logs(self):
        user_id = f"user-{uuid4()}"
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(_builtin(),)),
            patch(
                _GET_SKILLS_FOR_AGENT,
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo connection reset"),
            ),
            patch("app.agents.skills.discovery.log") as mock_log,
        ):
            result = await get_available_skills_text(user_id, "executor")

        assert "Test Skill" in result
        assert "does a thing" in result
        mock_log.warning.assert_called_once()
        kwargs = mock_log.warning.call_args.kwargs
        assert "mongo connection reset" in kwargs.get("error", ""), (
            f"the swallowed exception must be named in the log, got: {kwargs}"
        )

    async def test_mongo_failure_with_no_builtins_returns_empty_string(self):
        """A non-executor agent has no builtins merged in here (integration
        subagents get theirs from a different code path) — if Mongo also
        fails, there is nothing to show, and that must not raise."""
        user_id = f"user-{uuid4()}"
        with (
            patch(
                _GET_SKILLS_FOR_AGENT,
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch("app.agents.skills.discovery.log"),
        ):
            result = await get_available_skills_text(user_id, "gmail_agent")

        assert result == ""


class TestSuccessfulMerge:
    async def test_executor_merges_builtins_and_user_skills(self):
        from app.agents.skills.models import Skill

        user_id = f"user-{uuid4()}"
        user_skill = Skill(
            id="sk_1",
            user_id=user_id,
            name="my-installed-skill",
            description="installed by the user",
            target="executor",
            license=None,
            compatibility=None,
            metadata={},
            allowed_tools=[],
            body_content="body",
            vfs_path="/skills/my-installed-skill",
            enabled=True,
            source="github",
            source_url=None,
            files=["SKILL.md"],
        )
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(_builtin(),)),
            patch(
                _GET_SKILLS_FOR_AGENT,
                new_callable=AsyncMock,
                return_value=[user_skill],
            ),
        ):
            result = await get_available_skills_text(user_id, "executor")

        assert "Test Skill" in result
        assert "my-installed-skill" in result

    async def test_no_skills_at_all_returns_empty_string(self):
        user_id = f"user-{uuid4()}"
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=()),
            patch(_GET_SKILLS_FOR_AGENT, new_callable=AsyncMock, return_value=[]),
        ):
            result = await get_available_skills_text(user_id, "executor")

        assert result == ""

    async def test_non_executor_agent_does_not_merge_builtins(self):
        """Integration subagents get their builtins from a different code path
        (system_docs.integration_skills_block) — merging here too would list
        them twice."""
        user_id = f"user-{uuid4()}"
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(_builtin(),)),
            patch(_GET_SKILLS_FOR_AGENT, new_callable=AsyncMock, return_value=[]),
        ):
            result = await get_available_skills_text(user_id, "gmail_agent")

        assert result == ""
