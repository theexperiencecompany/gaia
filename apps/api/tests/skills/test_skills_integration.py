"""
Integration tests for skills prompt injection (Phase 3 flat schema).

These tests verify that skills are correctly injected into executor and subagent prompts.
They test the full flow from skills storage to prompt injection using the
flat schema and unified $or query.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.skills.discovery import _format_skills, get_available_skills_text
from app.agents.skills.models import Skill, SkillSource


def _make_skill(
    name: str = "test-skill",
    description: str = "A test skill",
    target: str = "executor",
    user_id: str = "user123",
    files: list[str] | None = None,
    vfs_path: str | None = None,
) -> Skill:
    """Helper to create a Skill instance with flat fields."""
    return Skill(
        id=f"skill_{name}",
        user_id=user_id,
        name=name,
        description=description,
        target=target,
        vfs_path=vfs_path or f"/users/{user_id}/skills/{target}/{name}",
        source=SkillSource.INLINE,
        files=files or ["SKILL.md"],
    )


class TestSkillsIntegrationFlow:
    """Integration tests for skills from DB to prompt injection."""

    @pytest.mark.asyncio
    async def test_executor_gets_skills_from_unified_query(self):
        """Executor should get skills via single unified $or query."""
        user_skill = _make_skill(
            name="my-executor-skill",
            description="User's custom executor skill",
            target="executor",
        )
        system_skill = _make_skill(
            name="system-skill",
            description="System skill",
            target="executor",
            user_id="system",
            vfs_path="/system/skills/executor/system-skill",
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [user_skill, system_skill]

            result = await get_available_skills_text("user123", "executor")

            assert "my-executor-skill" in result
            assert "system-skill" in result
            assert "Available Skills:" in result
            # Verify single call (no separate system skills query)
            mock_get.assert_called_once_with("user123", "executor")

    @pytest.mark.asyncio
    async def test_subagent_gets_only_own_target_skills(self):
        """Subagent should get only skills with its exact target agent_name."""
        gmail_skill = _make_skill(
            name="gmail-compose",
            description="Compose Gmail emails",
            target="gmail_agent",
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [gmail_skill]

            result = await get_available_skills_text("user123", "gmail_agent")

            assert "gmail-compose" in result
            mock_get.assert_called_once_with("user123", "gmail_agent")

    @pytest.mark.asyncio
    async def test_skills_text_format_plain_text(self):
        """Skills text should be plain text (not XML) with name, description, location."""
        skill = _make_skill(
            name="test-skill",
            description="Test skill description",
            files=["SKILL.md", "scripts/run.py"],
        )

        result = _format_skills([skill])

        assert "Available Skills:" in result
        assert "- test-skill: Test skill description" in result
        assert "Location:" in result
        assert "SKILL.md" in result
        assert "Resources: scripts/run.py" in result
        # Should NOT contain XML tags
        assert "<" not in result
        assert ">" not in result

    @pytest.mark.asyncio
    async def test_no_target_field_in_skill_output(self):
        """Output descriptions should NOT include the target field."""
        skill = _make_skill(name="github-pr", target="github_agent")

        result = _format_skills([skill])

        # "Target:" should not appear in the output
        assert "Target:" not in result

    @pytest.mark.asyncio
    async def test_context_message_building_includes_skills(self):
        """Context message builder should include skills text section."""
        skill = _make_skill(name="test-skill")

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [skill]

            result = await get_available_skills_text("user123", "executor")

            assert "test-skill" in result
            assert "Available Skills:" in result


class TestSkillsFilteringByAgent:
    """Tests for skills filtering based on agent type."""

    @pytest.mark.asyncio
    async def test_exact_agent_name_matching(self):
        """Query should use exact agent_name, no normalization."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            from app.agents.skills.registry import get_skills_for_agent

            await get_skills_for_agent("user123", "gmail_agent")

            call_query = mock_collection.find.call_args[0][0]
            # Exact match on "target" field (flat schema)
            assert call_query["target"] == "gmail_agent"
            # No $in, no "skill_metadata.target"
            assert "skill_metadata.target" not in call_query

    @pytest.mark.asyncio
    async def test_no_global_skills_leak(self):
        """Query should never include 'global' target — global skills are dead."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            from app.agents.skills.registry import get_skills_for_agent

            await get_skills_for_agent("user123", "github_agent")

            call_query = mock_collection.find.call_args[0][0]
            assert "global" not in str(call_query)

    @pytest.mark.asyncio
    async def test_disabled_skills_not_returned(self):
        """Disabled skills should be filtered out by the query."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            from app.agents.skills.registry import get_skills_for_agent

            await get_skills_for_agent("user123", "executor")

            call_query = mock_collection.find.call_args[0][0]
            assert call_query.get("enabled") is True


class TestSkillsEdgeCases:
    """Edge case tests for skills system."""

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_empty(self):
        """Empty user ID should return empty skills string."""
        result = await get_available_skills_text("", "executor")
        assert result == ""

    @pytest.mark.asyncio
    async def test_none_user_id_returns_empty(self):
        """None user ID should return empty skills string."""
        result = await get_available_skills_text(None, "executor")  # type: ignore
        assert result == ""

    @pytest.mark.asyncio
    async def test_multiple_skills_same_agent(self):
        """Multiple skills for the same agent should all appear."""
        skills = [
            _make_skill(name="skill-a", target="github_agent"),
            _make_skill(name="skill-b", target="github_agent"),
            _make_skill(name="skill-c", target="github_agent"),
        ]

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = skills

            result = await get_available_skills_text("user123", "github_agent")

            assert "skill-a" in result
            assert "skill-b" in result
            assert "skill-c" in result
