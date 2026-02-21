"""
Tests for Agent Skills system (Phase 3 flat schema).

These tests verify:
1. Skills are stored correctly in MongoDB with flat schema (registry)
2. Skills are discovered via unified $or query (system + user)
3. Skills text is generated correctly for prompt injection
4. Skills target matching uses exact agent_name (no normalization)

Tests use mocked MongoDB collections to avoid requiring a real database.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.agents.skills.discovery import get_available_skills_text
from app.agents.skills.models import Skill, SkillMetadata, SkillSource
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


def _make_skill_doc(
    skill_id: str = "skill_1",
    user_id: str = "user123",
    name: str = "test-skill",
    description: str = "A test skill",
    target: str = "executor",
    source: str = "inline",
    enabled: bool = True,
    vfs_path: str | None = None,
) -> dict:
    """Helper to create a flat-schema skill document."""
    return {
        "_id": skill_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "target": target,
        "auto_invoke": True,
        "license": None,
        "compatibility": None,
        "metadata": {},
        "allowed_tools": [],
        "body_content": f"Instructions for {name}",
        "vfs_path": vfs_path or f"/users/{user_id}/skills/{target}/{name}",
        "source": source,
        "source_url": None,
        "enabled": enabled,
        "installed_at": "2024-01-01T00:00:00+00:00",
        "updated_at": None,
        "files": ["SKILL.md"],
    }


class TestSkillsRegistryCRUD:
    """Tests for skills registry CRUD operations with flat schema."""

    @pytest.mark.asyncio
    async def test_install_skill_creates_flat_document(self, mock_skills_collection):
        """Installing a skill should create a flat MongoDB document."""
        mock_skills_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await install_skill(
                user_id="user123",
                name="test-skill",
                description="A test skill for unit testing",
                target="executor",
                vfs_path="/users/user123/skills/executor/test-skill",
                source=SkillSource.INLINE,
            )

            assert result.user_id == "user123"
            assert result.name == "test-skill"
            assert result.description == "A test skill for unit testing"
            assert result.target == "executor"
            assert result.enabled is True
            assert result.id is not None
            mock_skills_collection.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_install_skill_flat_kwargs(self, mock_skills_collection):
        """install_skill takes flat kwargs, not a SkillMetadata object."""
        mock_skills_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await install_skill(
                user_id="user123",
                name="github-pr",
                description="Create GitHub PRs",
                target="github_agent",
                vfs_path="/users/user123/skills/github_agent/github-pr",
                source=SkillSource.GITHUB,
                source_url="https://github.com/owner/repo",
                auto_invoke=True,
                metadata={"author": "test"},
                allowed_tools=["create_pull_request"],
            )

            assert result.name == "github-pr"
            assert result.target == "github_agent"
            assert result.source == SkillSource.GITHUB
            assert result.metadata == {"author": "test"}
            assert result.allowed_tools == ["create_pull_request"]

    @pytest.mark.asyncio
    async def test_install_skill_rejects_duplicate(self, mock_skills_collection):
        """Installing duplicate skill (same name+user_id+target) should raise ValueError."""
        mock_skills_collection.find_one = AsyncMock(
            return_value={"_id": "existing_skill_id", "user_id": "user123"}
        )

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            with pytest.raises(ValueError, match="already installed"):
                await install_skill(
                    user_id="user123",
                    name="existing-skill",
                    description="Already installed",
                    target="executor",
                    vfs_path="/path/to/skill",
                    source=SkillSource.INLINE,
                )

    @pytest.mark.asyncio
    async def test_install_skill_duplicate_check_query(self, mock_skills_collection):
        """Duplicate check should query by (user_id, name, target)."""
        mock_skills_collection.find_one = AsyncMock(return_value=None)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            await install_skill(
                user_id="user123",
                name="my-skill",
                description="Test",
                target="gmail_agent",
                vfs_path="/path",
                source=SkillSource.INLINE,
            )

            find_one_query = mock_skills_collection.find_one.call_args[0][0]
            assert find_one_query == {
                "user_id": "user123",
                "name": "my-skill",
                "target": "gmail_agent",
            }

    @pytest.mark.asyncio
    async def test_get_skill_by_id(self, mock_skills_collection):
        """Get skill by ID should return a Skill with flat fields."""
        doc = _make_skill_doc(
            skill_id="skill_123",
            name="test-skill",
            vfs_path="/users/user123/skills/executor/test-skill",
        )
        mock_skills_collection.find_one = AsyncMock(return_value=doc)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            result = await get_skill("user123", "skill_123")

            assert result is not None
            assert result.id == "skill_123"
            assert result.name == "test-skill"
            assert result.target == "executor"

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
        """List skills should return all skills for a user with flat fields."""
        docs = [
            _make_skill_doc(skill_id="skill_1", name="skill-one"),
            _make_skill_doc(skill_id="skill_2", name="skill-two"),
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
            assert result[0].name == "skill-one"
            assert result[1].name == "skill-two"

    @pytest.mark.asyncio
    async def test_list_skills_filter_by_target(self, mock_skills_collection):
        """List skills should filter by target when specified."""
        docs = [
            _make_skill_doc(
                skill_id="skill_1", name="executor-skill", target="executor"
            ),
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
            assert result[0].target == "executor"

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


class TestSkillsAgentFiltering:
    """Tests for skills filtering by agent — exact match, no normalization."""

    @pytest.mark.asyncio
    async def test_get_skills_for_agent_exact_target_match(
        self, mock_skills_collection
    ):
        """get_skills_for_agent should query with exact target match."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            await get_skills_for_agent("user123", "gmail_agent")

            call_query = mock_skills_collection.find.call_args[0][0]
            # Should use exact target match, not $in
            assert call_query["target"] == "gmail_agent"
            assert "$in" not in str(call_query)

    @pytest.mark.asyncio
    async def test_get_skills_for_agent_unified_query(self, mock_skills_collection):
        """get_skills_for_agent should use $or for user + system skills."""
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
            assert "$or" in call_query
            assert {"user_id": "user123"} in call_query["$or"]
            assert {"user_id": "system"} in call_query["$or"]

    @pytest.mark.asyncio
    async def test_get_skills_for_agent_filters_enabled_only(
        self, mock_skills_collection
    ):
        """get_skills_for_agent should only return enabled skills."""
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
            assert call_query["enabled"] is True

    @pytest.mark.asyncio
    async def test_no_global_target_in_query(self, mock_skills_collection):
        """Query should never include 'global' as a target."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            await get_skills_for_agent("user123", "github_agent")

            call_query = mock_skills_collection.find.call_args[0][0]
            assert "global" not in str(call_query)

    @pytest.mark.asyncio
    async def test_agent_name_used_directly_no_normalization(
        self, mock_skills_collection
    ):
        """Agent name should be passed directly — no stripping _agent suffix."""
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_skills_collection.find = MagicMock(return_value=mock_cursor)

        with patch(
            "app.agents.skills.registry._get_collection",
            return_value=mock_skills_collection,
        ):
            # Pass "github_agent" — it should stay as "github_agent", not become "github"
            await get_skills_for_agent("user123", "github_agent")

            call_query = mock_skills_collection.find.call_args[0][0]
            assert call_query["target"] == "github_agent"


class TestSkillsDiscoveryTextGeneration:
    """Tests for skills text generation for prompt injection."""

    @pytest.mark.asyncio
    async def test_generates_text_with_flat_fields(self):
        """Generated text should use flat Skill fields (name, description, vfs_path)."""
        skill = Skill(
            id="skill_1",
            user_id="user123",
            name="user-skill",
            description="User installed skill",
            target="executor",
            vfs_path="/users/user123/skills/executor/user-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [skill]

            result = await get_available_skills_text("user123", "executor")

            assert "Available Skills:" in result
            assert "user-skill" in result
            assert "User installed skill" in result
            assert "/users/user123/skills/executor/user-skill/SKILL.md" in result

    @pytest.mark.asyncio
    async def test_includes_extra_resources(self):
        """Generated text should list extra files beyond SKILL.md."""
        skill = Skill(
            id="skill_1",
            user_id="user123",
            name="test-skill",
            description="Test skill",
            target="executor",
            vfs_path="/users/user123/skills/executor/test-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md", "scripts/run.py", "templates/email.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [skill]

            result = await get_available_skills_text("user123", "executor")

            assert "Resources:" in result
            assert "scripts/run.py" in result

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_skills(self):
        """Should return empty string when no skills exist."""
        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = []

            result = await get_available_skills_text("user123", "executor")
            assert result == ""

    @pytest.mark.asyncio
    async def test_system_and_user_skills_unified(self):
        """Both system and user skills should appear in the same output."""
        system_skill = Skill(
            id="sys_1",
            user_id="system",
            name="create-pr",
            description="Create GitHub PRs",
            target="github_agent",
            vfs_path="/system/skills/github_agent/create-pr",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )
        user_skill = Skill(
            id="usr_1",
            user_id="user123",
            name="my-pr-template",
            description="Custom PR template",
            target="github_agent",
            vfs_path="/users/user123/skills/github_agent/my-pr-template",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [system_skill, user_skill]

            result = await get_available_skills_text("user123", "github_agent")

            assert "create-pr" in result
            assert "my-pr-template" in result


class TestSkillsPromptInjection:
    """Tests for skills injection into executor and subagent prompts."""

    @pytest.mark.asyncio
    async def test_skills_injected_for_executor(self):
        """Skills should be injected for executor agent."""
        skill = Skill(
            id="skill_1",
            user_id="user123",
            name="executor-skill",
            description="Executor skill",
            target="executor",
            vfs_path="/users/user123/skills/executor/executor-skill",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [skill]

            result = await get_available_skills_text("user123", "executor")
            assert "executor-skill" in result

    @pytest.mark.asyncio
    async def test_skills_injected_for_subagent(self):
        """Skills should be injected for a specific subagent by agent_name."""
        skill = Skill(
            id="skill_1",
            user_id="user123",
            name="gmail-compose",
            description="Gmail skill",
            target="gmail_agent",
            vfs_path="/users/user123/skills/gmail_agent/gmail-compose",
            source=SkillSource.INLINE,
            files=["SKILL.md"],
        )

        with patch(
            "app.agents.skills.discovery.get_skills_for_agent", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = [skill]

            result = await get_available_skills_text("user123", "gmail_agent")
            assert "gmail-compose" in result


class TestSkillModelsValidation:
    """Tests for Skill and SkillMetadata model validation."""

    def test_skill_model_flat_fields(self):
        """Skill model should have all fields at top level."""
        skill = Skill(
            id="test-id",
            user_id="user123",
            name="test-skill",
            description="A test skill",
            target="executor",
            vfs_path="/path/to/skill",
            source=SkillSource.INLINE,
        )

        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.target == "executor"
        assert skill.auto_invoke is True
        assert skill.enabled is True
        assert skill.metadata == {}
        assert skill.allowed_tools == []

    def test_skill_default_target_is_executor(self):
        """Default target should be 'executor', not 'global'."""
        skill = Skill(
            user_id="user123",
            name="test-skill",
            description="Test",
            vfs_path="/path",
            source=SkillSource.INLINE,
        )
        assert skill.target == "executor"

    def test_skill_metadata_default_target_is_executor(self):
        """SkillMetadata default target should be 'executor'."""
        meta = SkillMetadata(name="test-skill", description="Test")
        assert meta.target == "executor"

    def test_skill_name_validation_rejects_uppercase(self):
        """Name should reject uppercase."""
        with pytest.raises(ValueError, match="lowercase"):
            Skill(
                user_id="u",
                name="Bad-Name",
                description="Test",
                vfs_path="/p",
                source=SkillSource.INLINE,
            )

    def test_skill_name_validation_rejects_consecutive_hyphens(self):
        """Name should reject consecutive hyphens."""
        with pytest.raises(ValueError, match="consecutive"):
            Skill(
                user_id="u",
                name="bad--name",
                description="Test",
                vfs_path="/p",
                source=SkillSource.INLINE,
            )

    def test_skill_description_required(self):
        """Description should not be empty."""
        with pytest.raises(ValueError):
            Skill(
                user_id="u",
                name="test",
                description="",
                vfs_path="/p",
                source=SkillSource.INLINE,
            )


class TestSkillsEdgeCases:
    """Edge case tests for skills system."""

    @pytest.mark.asyncio
    async def test_empty_user_id_returns_empty_skills(self):
        """Empty user ID should return empty skills string."""
        result = await get_available_skills_text("", "executor")
        assert result == ""

    @pytest.mark.asyncio
    async def test_disabled_skills_filtered_in_query(self, mock_skills_collection):
        """Query should always include enabled=True."""
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
