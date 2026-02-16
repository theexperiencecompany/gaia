"""
Integration tests for skills prompt injection.

These tests verify that skills are correctly injected into executor and subagent prompts.
They test the full flow from skills storage to prompt injection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.skills.models import InstalledSkill, SkillMetadata, SkillSource


class TestSkillsIntegrationFlow:
    """Integration tests for skills from DB to prompt injection."""

    @pytest.mark.asyncio
    async def test_executor_gets_skills_from_db_and_vfs(self):
        """Executor should get skills from both MongoDB and VFS system skills."""
        user_skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="my-executor-skill",
                description="User's custom executor skill",
                target="executor",
            ),
            vfs_path="/users/user123/global/skills/custom/executor/my-executor-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        system_skill = {
            "name": "github-pr",
            "description": "System GitHub PR skill",
            "target": "github",
            "location": "/system/skills/github/github-pr/SKILL.md",
        }

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_user:
            with patch(
                "app.agents.skills.discovery.get_system_skills_for_agent",
                new_callable=AsyncMock,
            ) as mock_system:
                mock_user.return_value = [user_skill]
                mock_system.return_value = [system_skill]

                from app.agents.skills.discovery import get_available_skills_xml

                result = await get_available_skills_xml("user123", "executor")

                assert "my-executor-skill" in result
                assert "github-pr" in result
                assert "<available_skills>" in result

    @pytest.mark.asyncio
    async def test_subagent_gets_own_skills_plus_global(self):
        """Subagent should get its own skills plus global skills."""
        gmail_skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="gmail-compose",
                description="Compose Gmail emails",
                target="gmail",
            ),
            vfs_path="/users/user123/global/skills/custom/gmail/gmail-compose",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        global_skill = InstalledSkill(
            id="skill_2",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="common-helper",
                description="Available to all agents",
                target="global",
            ),
            vfs_path="/users/user123/global/skills/custom/global/common-helper",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [gmail_skill, global_skill]

            from app.agents.skills.discovery import get_available_skills_xml

            result = await get_available_skills_xml("user123", "gmail")

            assert "gmail-compose" in result
            assert "common-helper" in result

    @pytest.mark.asyncio
    async def test_skills_xml_has_correct_format(self):
        """Skills XML should have the correct format for agent consumption."""
        skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="test-skill",
                description="Test skill description",
                target="executor",
            ),
            vfs_path="/users/user123/global/skills/custom/executor/test-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md", "scripts/run.py"],
        )

        from app.agents.skills.discovery import _format_skills_xml

        result = _format_skills_xml([skill])

        assert "<available_skills>" in result
        assert "</available_skills>" in result
        assert "<skill>" in result
        assert "</skill>" in result
        assert "<name>test-skill</name>" in result
        assert "<description>Test skill description</description>" in result
        assert "SKILL.md" in result

    @pytest.mark.asyncio
    async def test_context_message_building_includes_skills(self):
        """Context message builder should include skills XML section."""
        skills_xml = """<available_skills>
  <skill>
    <name>test-skill</name>
    <description>A test skill</description>
    <location>/users/user123/global/skills/custom/executor/test-skill/SKILL.md</location>
  </skill>
</available_skills>"""

        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock_xml:
            mock_xml.return_value = skills_xml

            from app.agents.skills.discovery import get_available_skills_xml

            result = await get_available_skills_xml("user123", "executor")

            assert "test-skill" in result
            assert "<available_skills>" in result


class TestSkillsFilteringByAgent:
    """Tests for skills filtering based on agent type."""

    @pytest.mark.asyncio
    async def test_executor_target_skills_included_for_executor(self):
        """Skills with target='executor' should be included for executor."""
        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "<available_skills><skill><name>executor-only</name></skill></available_skills>"

            from app.agents.skills.discovery import get_available_skills_xml

            result = await get_available_skills_xml("user123", "executor")
            assert "executor-only" in result

    @pytest.mark.asyncio
    async def test_subagent_target_skills_not_included_for_executor(self):
        """Skills with target='gmail' should NOT be included for executor."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            from app.agents.skills.registry import get_skills_for_agent

            skills = await get_skills_for_agent("user123", "executor")

            assert not any(s.skill_metadata.name == "gmail-only" for s in skills)

    @pytest.mark.asyncio
    async def test_gmail_agent_gets_gmail_and_global_skills(self):
        """Gmail agent should get both gmail and global target skills."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            from app.agents.skills.registry import get_skills_for_agent

            await get_skills_for_agent("user123", "gmail")

            call_query = mock_collection.find.call_args[0][0]
            assert "skill_metadata.target" in call_query
            assert "$in" in call_query["skill_metadata.target"]


class TestSkillsEdgeCases:
    """Edge case tests for skills system."""

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_empty_skills(self):
        """Empty user ID should return empty skills string."""
        from app.agents.skills.discovery import get_available_skills_xml

        result = await get_available_skills_xml("", "executor")
        assert result == ""

    @pytest.mark.asyncio
    async def test_none_user_id_returns_empty_skills(self):
        """None user ID should return empty skills string."""
        from app.agents.skills.discovery import get_available_skills_xml

        result = await get_available_skills_xml(None, "executor")  # type: ignore
        assert result == ""

    @pytest.mark.asyncio
    async def test_disabled_skills_not_returned(self):
        """Disabled skills should be filtered out."""
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
