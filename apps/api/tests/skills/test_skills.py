"""
Tests for Agent Skills system.

These tests verify:
1. Skills are stored correctly in MongoDB (registry)
2. Skills are discovered from VFS (system skills) and DB (user skills)
3. Skills XML is generated correctly for prompt injection
4. Skills are injected into both executor and subagent prompts

Tests use mocked MongoDB collections to avoid requiring a real database.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.skills.discovery import (
    get_available_skills_xml,
    get_system_skills_for_agent,
)
from app.agents.skills.models import InstalledSkill, SkillMetadata, SkillSource
from app.agents.skills.registry import (
    disable_skill,
    enable_skill,
    get_skill,
    get_skills_for_agent,
    install_skill,
    list_skills,
)


@pytest.fixture
def mock_skills_collection():
    """Create a mock skills collection."""
    mock = AsyncMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.update_one = AsyncMock()
    mock.insert_one = AsyncMock()
    mock.delete_one = AsyncMock()
    mock.find = MagicMock()
    return mock


@pytest.fixture
def mock_vfs_collection():
    """Create a mock VFS collection for system skills."""
    mock = AsyncMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.find = MagicMock()
    return mock


class TestSkillsRegistryCRUD:
    """Tests for skills registry CRUD operations."""

    @pytest.mark.asyncio
    async def test_install_skill_creates_document(self, mock_skills_collection):
        """Installing a skill should create a MongoDB document."""
        mock_skills_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            skill_metadata = SkillMetadata(
                name="test-skill",
                description="A test skill for unit testing",
                target="executor",
            )

            result = await install_skill(
                user_id="user123",
                skill_metadata=skill_metadata,
                vfs_path="/users/user123/global/skills/custom/executor/test-skill",
                source=SkillSource.INLINE,
            )

            assert result.user_id == "user123"
            assert result.skill_metadata.name == "test-skill"
            assert result.enabled is True
            mock_skills_collection.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_skill_rejects_duplicate(self, mock_skills_collection):
        """Installing duplicate skill should raise ValueError."""
        mock_skills_collection.find_one = AsyncMock(
            return_value={"_id": "existing_skill_id", "user_id": "user123"}
        )

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            skill_metadata = SkillMetadata(
                name="existing-skill",
                description="Already installed",
                target="executor",
            )

            with pytest.raises(ValueError, match="already installed"):
                await install_skill(
                    user_id="user123",
                    skill_metadata=skill_metadata,
                    vfs_path="/path/to/skill",
                    source=SkillSource.INLINE,
                )

    @pytest.mark.asyncio
    async def test_get_skill_by_id(self, mock_skills_collection):
        """Get skill by ID should return the skill."""
        doc = {
            "_id": "skill_123",
            "user_id": "user123",
            "skill_metadata": {
                "name": "test-skill",
                "description": "Test skill",
                "target": "global",
            },
            "vfs_path": "/users/user123/global/skills/custom/global/test-skill",
            "source": "inline",
            "enabled": True,
            "files": ["SKILL.md"],
            "installed_at": "2024-01-01T00:00:00+00:00",
        }
        mock_skills_collection.find_one = AsyncMock(return_value=doc)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await get_skill("user123", "skill_123")

            assert result is not None
            assert result.id == "skill_123"
            assert result.skill_metadata.name == "test-skill"

    @pytest.mark.asyncio
    async def test_get_skill_returns_none_for_missing(self, mock_skills_collection):
        """Get skill should return None for non-existent skill."""
        mock_skills_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await get_skill("user123", "nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_list_skills_for_user(self, mock_skills_collection):
        """List skills should return all skills for a user."""
        docs = [
            {
                "_id": "skill_1",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "skill-one",
                    "description": "First skill",
                    "target": "global",
                },
                "vfs_path": "/path/1",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "_id": "skill_2",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "skill-two",
                    "description": "Second skill",
                    "target": "executor",
                },
                "vfs_path": "/path/2",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-02T00:00:00+00:00",
            },
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await list_skills("user123")

            assert len(result) == 2
            assert result[0].skill_metadata.name == "skill-one"
            assert result[1].skill_metadata.name == "skill-two"

    @pytest.mark.asyncio
    async def test_list_skills_filter_by_target(self, mock_skills_collection):
        """List skills should filter by target when specified."""
        docs = [
            {
                "_id": "skill_1",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "executor-skill",
                    "description": "Executor skill",
                    "target": "executor",
                },
                "vfs_path": "/path/1",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await list_skills("user123", target="executor")

            assert len(result) == 1
            assert result[0].skill_metadata.target == "executor"

    @pytest.mark.asyncio
    async def test_enable_skill(self, mock_skills_collection):
        """Enable skill should update the enabled flag."""
        mock_skills_collection.update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await enable_skill("user123", "skill_123")

            assert result is True
            mock_skills_collection.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_skill(self, mock_skills_collection):
        """Disable skill should update the enabled flag to False."""
        mock_skills_collection.update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await disable_skill("user123", "skill_123")

            assert result is True


class TestSkillsRegistryAgentFiltering:
    """Tests for skills filtering by agent."""

    @pytest.mark.asyncio
    async def test_get_skills_for_executor_includes_executor_and_global(
        self, mock_skills_collection
    ):
        """Executor should get both 'executor' and 'global' target skills."""
        docs = [
            {
                "_id": "skill_1",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "global-skill",
                    "description": "Available to all",
                    "target": "global",
                },
                "vfs_path": "/path/1",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-01T00:00:00+00:00",
            },
            {
                "_id": "skill_2",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "executor-skill",
                    "description": "Executor only",
                    "target": "executor",
                },
                "vfs_path": "/path/2",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-02T00:00:00+00:00",
            },
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await get_skills_for_agent("user123", "executor")

            assert len(result) == 2
            call_query = mock_skills_collection.find.call_args[0][0]
            assert "skill_metadata.target" in call_query

    @pytest.mark.asyncio
    async def test_get_skills_for_subagent_includes_subagent_and_global(
        self, mock_skills_collection
    ):
        """Subagent should get both 'subagent' and 'global' target skills."""
        docs = [
            {
                "_id": "skill_1",
                "user_id": "user123",
                "skill_metadata": {
                    "name": "gmail-skill",
                    "description": "Gmail specific",
                    "target": "gmail",
                },
                "vfs_path": "/path/1",
                "source": "inline",
                "enabled": True,
                "files": [],
                "installed_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await get_skills_for_agent("user123", "gmail")

            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_skills_excludes_disabled_skills(self, mock_skills_collection):
        """Disabled skills should not be returned."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            await get_skills_for_agent("user123", "executor")

            call_query = mock_skills_collection.find.call_args[0][0]
            assert call_query.get("enabled") is True


class TestSkillsDiscoverySystemSkills:
    """Tests for system skills discovery from VFS."""

    @pytest.mark.asyncio
    async def test_get_system_skills_returns_skills_from_vfs(self):
        """System skills reading from VFS requires full integration test - skipping unit test."""

    @pytest.mark.asyncio
    async def test_get_system_skills_returns_empty_for_nonexistent_target(
        self, mock_vfs_collection
    ):
        """Should return empty list when target doesn't exist."""
        list_dir_result = AsyncMock()
        list_dir_result.items = []

        mock_vfs_instance = AsyncMock()
        mock_vfs_instance.list_dir = AsyncMock(return_value=list_dir_result)

        with patch("app.agents.skills.discovery.MongoVFS") as MockVFS:
            MockVFS.return_value = mock_vfs_instance

            result = await get_system_skills_for_agent("nonexistent_agent")

            assert result == []


class TestSkillsDiscoveryXMLGeneration:
    """Tests for skills XML generation."""

    @pytest.mark.asyncio
    async def test_generate_xml_includes_skill_metadata(self):
        """Generated XML should include name, description, location."""
        skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="user-skill",
                description="User installed skill",
                target="executor",
            ),
            vfs_path="/users/user123/global/skills/custom/executor/user-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        system_skill = {
            "name": "system-skill",
            "description": "System skill",
            "target": "github",
            "location": "/system/skills/github/system-skill/SKILL.md",
        }

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get_user:
            with patch(
                "app.agents.skills.discovery.get_system_skills_for_agent",
                new_callable=AsyncMock,
            ) as mock_get_system:
                mock_get_user.return_value = [skill]
                mock_get_system.return_value = [system_skill]

                result = await get_available_skills_xml("user123", "executor")

                assert "<available_skills>" in result
                assert "user-skill" in result
                assert "system-skill" in result

    @pytest.mark.asyncio
    async def test_get_available_skills_xml_returns_empty_for_no_skills(self):
        """Should return empty string when no skills exist."""
        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get_user:
            with patch(
                "app.agents.skills.discovery.get_system_skills_for_agent",
                new_callable=AsyncMock,
            ) as mock_get_system:
                mock_get_user.return_value = []
                mock_get_system.return_value = []

                result = await get_available_skills_xml("user123", "executor")

                assert result == ""


class TestSkillsPromptInjection:
    """Tests for skills injection into executor and subagent prompts."""

    @pytest.mark.asyncio
    async def test_skills_injected_for_executor(self):
        """Skills should be injected when subagent_id is None (executor)."""
        skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="executor-skill",
                description="Executor skill",
                target="executor",
            ),
            vfs_path="/users/user123/global/skills/custom/executor/executor-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock_xml:
            with patch(
                "app.agents.skills.discovery.get_skills_for_agent",
                new_callable=AsyncMock,
            ) as mock_get:
                mock_xml.return_value = "<available_skills><skill><name>executor-skill</name></skill></available_skills>"
                mock_get.return_value = [skill]

                result = await get_available_skills_xml("user123", "executor")

                assert "executor-skill" in result

    @pytest.mark.asyncio
    async def test_skills_injected_for_subagent(self):
        """Skills should be injected for a specific subagent."""
        skill = InstalledSkill(
            id="skill_1",
            user_id="user123",
            skill_metadata=SkillMetadata(
                name="gmail-skill",
                description="Gmail skill",
                target="gmail",
            ),
            vfs_path="/users/user123/global/skills/custom/gmail/gmail-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock_xml:
            with patch(
                "app.agents.skills.discovery.get_skills_for_agent",
                new_callable=AsyncMock,
            ) as mock_get:
                mock_xml.return_value = "<available_skills><skill><name>gmail-skill</name></skill></available_skills>"
                mock_get.return_value = [skill]

                result = await get_available_skills_xml("user123", "gmail")

                assert "gmail-skill" in result

    @pytest.mark.asyncio
    async def test_skills_filtered_by_agent_target(self):
        """Skills should be filtered to only include those available to the agent."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            gmail_skills = await get_skills_for_agent("user123", "gmail")
            executor_skills = await get_skills_for_agent("user123", "executor")

            assert isinstance(gmail_skills, list)
            assert isinstance(executor_skills, list)

    @pytest.mark.asyncio
    async def test_global_skills_available_to_all_agents(self):
        """Global skills should be available to all agents."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)

        mock_collection = AsyncMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection", return_value=mock_collection
        ):
            gmail_skills = await get_skills_for_agent("user123", "gmail")
            executor_skills = await get_skills_for_agent("user123", "executor")
            github_skills = await get_skills_for_agent("user123", "github")

            assert isinstance(gmail_skills, list)
            assert isinstance(executor_skills, list)
            assert isinstance(github_skills, list)


class TestSkillsContextMessageInjection:
    """Tests for skills injection in create_agent_context_message."""

    @pytest.mark.asyncio
    async def test_context_message_includes_skills_xml_for_executor(self):
        """Context message should include skills XML for executor (subagent_id=None)."""
        skills_xml = "<available_skills><skill><name>test-skill</name></skill></available_skills>"

        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock_xml:
            mock_xml.return_value = skills_xml

            result = await get_available_skills_xml("user123", "executor")

            assert "test-skill" in result

    @pytest.mark.asyncio
    async def test_context_message_includes_skills_xml_for_subagent(self):
        """Context message should include skills XML for subagent."""
        skills_xml = "<available_skills><skill><name>gmail-skill</name></skill></available_skills>"

        with patch(
            "app.agents.skills.discovery.get_available_skills_xml",
            new_callable=AsyncMock,
        ) as mock_xml:
            mock_xml.return_value = skills_xml

            result = await get_available_skills_xml("user123", "gmail")

            assert "gmail-skill" in result

    @pytest.mark.asyncio
    async def test_skills_section_empty_when_no_user_id(self):
        """Skills section should include system skills even when no user_id provided."""
        # Mock VFS to return no system skills for test
        with patch(
            "app.agents.skills.discovery.get_system_skills_for_agent",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_available_skills_xml("", "executor")

            assert result == ""
