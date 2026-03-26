"""Unit tests for the skills registry CRUD operations."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.agents.skills.models import (
    Skill,
    SkillMetadata,
    SkillSource,
    _validate_skill_name,
    _validate_skill_description,
)
from app.agents.skills.registry import (
    _doc_to_skill,
    _skill_to_doc,
    disable_skill,
    enable_skill,
    get_skill,
    get_skill_by_name,
    get_skills_for_agent,
    install_skill,
    list_skills,
    uninstall_skill,
)


@pytest.fixture
def sample_skill():
    return Skill(
        id="skill_001",
        user_id="user_123",
        name="my-skill",
        description="A test skill",
        target="executor",
        vfs_path="/skills/my-skill",
        source=SkillSource.GITHUB,
        enabled=True,
        installed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_doc():
    return {
        "_id": "skill_001",
        "user_id": "user_123",
        "name": "my-skill",
        "description": "A test skill",
        "target": "executor",
        "vfs_path": "/skills/my-skill",
        "source": "github",
        "enabled": True,
        "installed_at": "2024-01-01T00:00:00+00:00",
        "updated_at": None,
        "license": None,
        "compatibility": None,
        "metadata": {},
        "allowed_tools": [],
        "body_content": None,
        "source_url": None,
        "files": [],
    }


@pytest.mark.unit
class TestSkillNameValidation:
    def test_valid_names(self):
        assert _validate_skill_name("my-skill") == "my-skill"
        assert _validate_skill_name("a") == "a"
        assert _validate_skill_name("skill123") == "skill123"
        assert _validate_skill_name("my-cool-skill") == "my-cool-skill"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_skill_name("")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            _validate_skill_name("MySkill")

    def test_rejects_consecutive_hyphens(self):
        with pytest.raises(ValueError, match="consecutive hyphens"):
            _validate_skill_name("my--skill")

    def test_rejects_starting_with_hyphen(self):
        with pytest.raises(ValueError):
            _validate_skill_name("-skill")

    def test_rejects_ending_with_hyphen(self):
        with pytest.raises(ValueError):
            _validate_skill_name("skill-")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="at most 64"):
            _validate_skill_name("a" * 65)

    def test_rejects_special_characters(self):
        with pytest.raises(ValueError):
            _validate_skill_name("my_skill")

        with pytest.raises(ValueError):
            _validate_skill_name("my.skill")


@pytest.mark.unit
class TestSkillDescriptionValidation:
    def test_valid_description(self):
        assert (
            _validate_skill_description("Does something useful")
            == "Does something useful"
        )

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_skill_description("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_skill_description("   ")


@pytest.mark.unit
class TestSkillModel:
    def test_valid_skill(self, sample_skill):
        assert sample_skill.name == "my-skill"
        assert sample_skill.enabled is True
        assert sample_skill.source == SkillSource.GITHUB

    def test_default_target(self):
        s = Skill(
            user_id="u1",
            name="test",
            description="Test",
            vfs_path="/skills/test",
            source=SkillSource.INLINE,
        )
        assert s.target == "executor"

    def test_default_fields(self):
        s = Skill(
            user_id="u1",
            name="test",
            description="Test",
            vfs_path="/skills/test",
            source=SkillSource.INLINE,
        )
        assert s.metadata == {}
        assert s.allowed_tools == []
        assert s.files == []
        assert s.enabled is True

    def test_serializes_datetime(self, sample_skill):
        dumped = sample_skill.model_dump()
        assert isinstance(dumped["installed_at"], str)
        assert "2024-01-01" in dumped["installed_at"]

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Skill(name="test")

    def test_invalid_name_rejected(self):
        with pytest.raises(ValidationError):
            Skill(
                user_id="u1",
                name="INVALID",
                description="Test",
                vfs_path="/p",
                source=SkillSource.INLINE,
            )


@pytest.mark.unit
class TestSkillMetadata:
    def test_valid(self):
        m = SkillMetadata(name="my-skill", description="A skill")
        assert m.name == "my-skill"
        assert m.target == "executor"

    def test_with_optional_fields(self):
        m = SkillMetadata(
            name="my-skill",
            description="A skill",
            license="MIT",
            target="gmail_agent",
            allowed_tools=["search"],
        )
        assert m.license == "MIT"
        assert m.target == "gmail_agent"
        assert m.allowed_tools == ["search"]

    def test_invalid_name(self):
        with pytest.raises(ValidationError):
            SkillMetadata(name="BAD NAME", description="test")


@pytest.mark.unit
class TestSkillSource:
    def test_all_sources(self):
        assert SkillSource.GITHUB.value == "github"
        assert SkillSource.URL.value == "url"
        assert SkillSource.UPLOAD.value == "upload"
        assert SkillSource.INLINE.value == "inline"


@pytest.mark.unit
class TestSkillToDoc:
    def test_converts_skill_to_doc(self, sample_skill):
        doc = _skill_to_doc(sample_skill)

        assert doc["_id"] == "skill_001"
        assert "id" not in doc
        assert doc["user_id"] == "user_123"
        assert doc["name"] == "my-skill"

    def test_no_id_field_when_none(self):
        s = Skill(
            user_id="u1",
            name="test",
            description="Test",
            vfs_path="/p",
            source=SkillSource.INLINE,
        )
        doc = _skill_to_doc(s)
        assert "_id" not in doc


@pytest.mark.unit
class TestDocToSkill:
    def test_converts_doc_to_skill(self, sample_doc):
        skill = _doc_to_skill(sample_doc)

        assert skill.id == "skill_001"
        assert skill.name == "my-skill"
        assert skill.source == SkillSource.GITHUB
        assert isinstance(skill.installed_at, datetime)

    def test_handles_datetime_objects(self):
        doc = {
            "_id": "s1",
            "user_id": "u1",
            "name": "test",
            "description": "Test",
            "target": "executor",
            "vfs_path": "/p",
            "source": "inline",
            "enabled": True,
            "installed_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
            "updated_at": None,
            "license": None,
            "compatibility": None,
            "metadata": {},
            "allowed_tools": [],
            "body_content": None,
            "source_url": None,
            "files": [],
        }
        skill = _doc_to_skill(doc)
        assert skill.id == "s1"
        assert isinstance(skill.installed_at, datetime)


@pytest.mark.unit
class TestSkillRegistryCRUD:
    """Test the registry functions with mocked MongoDB collection."""

    @pytest.fixture
    def mock_collection(self):
        with patch("app.agents.skills.registry._get_collection") as mock_get:
            mock_col = MagicMock()
            mock_get.return_value = mock_col
            yield mock_col

    async def test_get_skill_found(self, mock_collection):
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "s1",
                "user_id": "u1",
                "name": "test",
                "description": "Test skill",
                "target": "executor",
                "vfs_path": "/skills/test",
                "source": "github",
                "enabled": True,
                "installed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": None,
                "license": None,
                "compatibility": None,
                "metadata": {},
                "allowed_tools": [],
                "body_content": None,
                "source_url": None,
                "files": [],
            }
        )

        skill = await get_skill("u1", "s1")

        assert skill is not None
        assert skill.id == "s1"
        assert skill.name == "test"
        mock_collection.find_one.assert_called_once_with({"_id": "s1", "user_id": "u1"})

    async def test_get_skill_not_found(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        skill = await get_skill("u1", "missing")
        assert skill is None

    async def test_uninstall_skill_success(self, mock_collection):
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        result = await uninstall_skill(user_id="u1", skill_id="s1")
        assert result is True

    async def test_uninstall_skill_not_found(self, mock_collection):
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        result = await uninstall_skill(user_id="u1", skill_id="missing")
        assert result is False

    async def test_enable_skill(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await enable_skill(user_id="test_user", skill_id="s1")
        assert result is True

        call_args = mock_collection.update_one.call_args[0]
        query_filter, update_doc = call_args
        assert query_filter["user_id"] == "test_user"  # security boundary
        assert query_filter["_id"] == "s1"
        assert update_doc["$set"]["enabled"] is True  # exact boolean value

    async def test_disable_skill(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await disable_skill(user_id="test_user", skill_id="s1")
        assert result is True

        call_args = mock_collection.update_one.call_args[0]
        query_filter, update_doc = call_args
        assert query_filter["user_id"] == "test_user"  # security boundary
        assert query_filter["_id"] == "s1"
        assert update_doc["$set"]["enabled"] is False  # exact boolean value

    async def test_enable_skill_not_found(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await enable_skill(user_id="u1", skill_id="missing")
        assert result is False

    async def test_list_skills(self, mock_collection):
        docs = [
            {
                "_id": f"s{i}",
                "user_id": "u1",
                "name": f"skill-{i}",
                "description": f"Skill {i}",
                "target": "executor",
                "vfs_path": f"/skills/skill-{i}",
                "source": "inline",
                "enabled": True,
                "installed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": None,
                "license": None,
                "compatibility": None,
                "metadata": {},
                "allowed_tools": [],
                "body_content": None,
                "source_url": None,
                "files": [],
            }
            for i in range(3)
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_collection.find.return_value = mock_cursor

        skills = await list_skills("u1")

        assert len(skills) == 3
        assert all(isinstance(s, Skill) for s in skills)

    async def test_list_skills_with_filters(self, mock_collection):
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value = mock_cursor

        await list_skills("u1", target="gmail_agent", enabled_only=True)

        call_args = mock_collection.find.call_args[0][0]
        assert call_args["user_id"] == "u1"
        assert call_args["target"] == "gmail_agent"
        assert call_args["enabled"] is True

    async def test_get_skill_by_name(self, mock_collection):
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "s1",
                "user_id": "u1",
                "name": "my-skill",
                "description": "Test",
                "target": "executor",
                "vfs_path": "/skills/my-skill",
                "source": "github",
                "enabled": True,
                "installed_at": "2024-01-01T00:00:00+00:00",
                "updated_at": None,
                "license": None,
                "compatibility": None,
                "metadata": {},
                "allowed_tools": [],
                "body_content": None,
                "source_url": None,
                "files": [],
            }
        )

        skill = await get_skill_by_name("u1", "my-skill")
        assert skill is not None
        assert skill.name == "my-skill"

    async def test_get_skill_by_name_with_target(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        await get_skill_by_name("u1", "my-skill", target="gmail_agent")

        call_args = mock_collection.find_one.call_args[0][0]
        assert call_args["target"] == "gmail_agent"


@pytest.mark.unit
class TestGetSkillsForAgent:
    """Test get_skills_for_agent — the cached path for agent skill lookup."""

    @pytest.fixture
    def mock_collection(self):
        with patch("app.agents.skills.registry._get_collection") as mock_get:
            mock_col = MagicMock()
            mock_get.return_value = mock_col
            yield mock_col

    @pytest.fixture(autouse=True)
    def bypass_cache(self):
        """Patch Redis cache helpers so tests always exercise the DB path."""
        with (
            patch(
                "app.decorators.caching.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            yield

    def _make_doc(
        self, skill_id: str, user_id: str, enabled: bool, agent_name: str
    ) -> dict:
        return {
            "_id": skill_id,
            "user_id": user_id,
            "name": f"skill-{skill_id}",
            "description": f"Skill {skill_id}",
            "target": agent_name,
            "vfs_path": f"/skills/skill-{skill_id}",
            "source": "inline",
            "enabled": enabled,
            "installed_at": "2024-01-01T00:00:00+00:00",
            "updated_at": None,
            "license": None,
            "compatibility": None,
            "metadata": {},
            "allowed_tools": [],
            "body_content": None,
            "source_url": None,
            "files": [],
        }

    async def test_queries_db_for_enabled_skills(self, mock_collection):
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value = mock_cursor

        await get_skills_for_agent(user_id="u1", agent_name="executor")

        query = mock_collection.find.call_args[0][0]
        assert query["enabled"] is True
        assert query["target"] == "executor"
        # Must scope to the requesting user AND system skills
        or_clause = query["$or"]
        user_ids_in_query = {clause["user_id"] for clause in or_clause}
        assert "u1" in user_ids_in_query
        assert "system" in user_ids_in_query

    async def test_returns_only_enabled_skills(self, mock_collection):
        # DB returns only enabled docs (the query already filters); verify
        # that all returned Skill objects are enabled.
        docs = [
            self._make_doc("s1", "u1", True, "executor"),
            self._make_doc("s2", "system", True, "executor"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=docs)
        mock_collection.find.return_value = mock_cursor

        skills = await get_skills_for_agent(user_id="u1", agent_name="executor")

        assert len(skills) == 2
        assert all(s.enabled is True for s in skills)
        assert all(isinstance(s, Skill) for s in skills)

    async def test_cache_hit_returns_without_db_call(self, mock_collection):
        """A warm cache short-circuits the DB entirely."""
        cached_skills = [
            Skill(
                id="s1",
                user_id="u1",
                name="cached-skill",
                description="From cache",
                target="executor",
                vfs_path="/skills/cached-skill",
                source=SkillSource.INLINE,
                enabled=True,
            )
        ]
        with patch(
            "app.decorators.caching.get_cache",
            new_callable=AsyncMock,
            return_value=cached_skills,
        ):
            result = await get_skills_for_agent(user_id="u1", agent_name="executor")

        mock_collection.find.assert_not_called()
        assert result == cached_skills


@pytest.mark.unit
class TestInstallSkill:
    """Test install_skill — document shape and return value."""

    @pytest.fixture
    def mock_collection(self):
        with patch("app.agents.skills.registry._get_collection") as mock_get:
            mock_col = MagicMock()
            mock_get.return_value = mock_col
            yield mock_col

    @pytest.fixture(autouse=True)
    def bypass_cache_invalidation(self):
        """Suppress Redis delete_cache calls from @CacheInvalidator."""
        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock):
            yield

    async def test_inserts_correct_document_shape(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)  # no duplicate
        mock_collection.insert_one = AsyncMock()

        await install_skill(
            user_id="u1",
            name="my-skill",
            description="Does something useful",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.GITHUB,
            source_url="https://github.com/org/repo",
            license="MIT",
        )

        mock_collection.insert_one.assert_called_once()
        inserted_doc = mock_collection.insert_one.call_args[0][0]

        assert inserted_doc["user_id"] == "u1"
        assert inserted_doc["name"] == "my-skill"
        assert inserted_doc["description"] == "Does something useful"
        assert inserted_doc["target"] == "executor"
        assert inserted_doc["vfs_path"] == "/skills/my-skill"
        assert inserted_doc["source"] == SkillSource.GITHUB
        assert inserted_doc["enabled"] is True
        assert "_id" in inserted_doc  # UUID assigned
        assert "id" not in inserted_doc  # flat schema: no separate id field

    async def test_returns_installed_skill(self, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="my-skill",
            description="Does something useful",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.INLINE,
        )

        assert isinstance(skill, Skill)
        assert skill.user_id == "u1"
        assert skill.name == "my-skill"
        assert skill.enabled is True
        assert skill.id is not None

    async def test_raises_on_duplicate(self, mock_collection):
        existing_doc = {
            "_id": "existing-id",
            "user_id": "u1",
            "name": "my-skill",
            "target": "executor",
        }
        mock_collection.find_one = AsyncMock(return_value=existing_doc)
        mock_collection.insert_one = AsyncMock()

        with pytest.raises(ValueError, match="already installed"):
            await install_skill(
                user_id="u1",
                name="my-skill",
                description="Duplicate skill",
                target="executor",
                vfs_path="/skills/my-skill",
                source=SkillSource.INLINE,
            )

        mock_collection.insert_one.assert_not_called()
