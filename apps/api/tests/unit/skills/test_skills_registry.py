"""Unit tests for the skills registry CRUD operations."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

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
        assert _validate_skill_description("Does something useful") == "Does something useful"

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
        mock_collection.find_one.assert_called_once_with(
            {"_id": "s1", "user_id": "u1"}
        )

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

        result = await enable_skill(user_id="u1", skill_id="s1")
        assert result is True

    async def test_disable_skill(self, mock_collection):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await disable_skill(user_id="u1", skill_id="s1")
        assert result is True

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
class TestInstallSkill:
    """Tests for install_skill() — duplicate detection, UUID generation,
    cache invalidation, optional parameters, and return value."""

    @pytest.fixture
    def mock_collection(self):
        with patch("app.agents.skills.registry._get_collection") as mock_get:
            mock_col = MagicMock()
            mock_get.return_value = mock_col
            yield mock_col

    @pytest.fixture
    def mock_cache_invalidator(self):
        """Suppress Redis calls made by the @CacheInvalidator decorator."""
        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as mock_del:
            yield mock_del

    async def test_install_skill_raises_on_duplicate(
        self, mock_collection, mock_cache_invalidator
    ):
        # First call: no existing skill found — succeeds.
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        await install_skill(
            user_id="u1",
            name="my-skill",
            description="A skill",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.INLINE,
        )

        # Second call: duplicate detected — find_one returns an existing doc.
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "existing-id",
                "user_id": "u1",
                "name": "my-skill",
                "target": "executor",
            }
        )

        with pytest.raises(ValueError, match="already installed"):
            await install_skill(
                user_id="u1",
                name="my-skill",
                description="A skill",
                target="executor",
                vfs_path="/skills/my-skill",
                source=SkillSource.INLINE,
            )

        # The second call must NOT have called insert_one because the duplicate
        # check raises before reaching the insert.
        mock_collection.insert_one.assert_called_once()

    async def test_install_skill_duplicate_check_uses_name_user_and_target(
        self, mock_collection, mock_cache_invalidator
    ):
        """Duplicate detection must query by user_id + name + target together."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        await install_skill(
            user_id="u1",
            name="my-skill",
            description="A skill",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.INLINE,
        )

        query = mock_collection.find_one.call_args[0][0]
        assert query["user_id"] == "u1"
        assert query["name"] == "my-skill"
        assert query["target"] == "executor"

    async def test_install_skill_generates_unique_uuid(
        self, mock_collection, mock_cache_invalidator
    ):
        """Each installed skill must receive a valid UUID as its id."""
        import re

        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="my-skill",
            description="A skill",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.INLINE,
        )

        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        assert skill.id is not None
        assert uuid_pattern.match(skill.id), f"'{skill.id}' is not a valid UUID v4"

    async def test_install_skill_generates_different_ids_each_call(
        self, mock_collection, mock_cache_invalidator
    ):
        """Two successive installs must produce distinct UUIDs."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill_a = await install_skill(
            user_id="u1",
            name="skill-a",
            description="Skill A",
            target="executor",
            vfs_path="/skills/skill-a",
            source=SkillSource.INLINE,
        )
        skill_b = await install_skill(
            user_id="u1",
            name="skill-b",
            description="Skill B",
            target="executor",
            vfs_path="/skills/skill-b",
            source=SkillSource.INLINE,
        )

        assert skill_a.id != skill_b.id

    async def test_install_skill_invalidates_cache(
        self, mock_collection, mock_cache_invalidator
    ):
        """install_skill must trigger cache invalidation for both key patterns."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        await install_skill(
            user_id="user-42",
            name="my-skill",
            description="A skill",
            target="executor",
            vfs_path="/skills/my-skill",
            source=SkillSource.INLINE,
        )

        # The @CacheInvalidator decorator expands _SKILLS_INVALIDATION_PATTERNS
        # using the function's arguments and calls delete_cache for each.
        deleted_keys = [call.args[0] for call in mock_cache_invalidator.call_args_list]
        assert any("user-42" in key for key in deleted_keys), (
            "Cache invalidation did not include the correct user_id"
        )
        # Both patterns must be invalidated.
        assert len(deleted_keys) == 2, (
            f"Expected 2 cache keys invalidated, got {len(deleted_keys)}: {deleted_keys}"
        )

    async def test_install_skill_with_all_optional_params(
        self, mock_collection, mock_cache_invalidator
    ):
        """All 6 optional parameters must be persisted on the returned Skill."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="full-skill",
            description="A fully specified skill",
            target="executor",
            vfs_path="/skills/full-skill",
            source=SkillSource.GITHUB,
            source_url="https://github.com/org/repo",
            body_content="# SKILL.md\nDoes stuff.",
            files=["main.py", "helper.py"],
            license="MIT",
            compatibility="python>=3.11",
            metadata={"version": "1.0", "author": "tester"},
            allowed_tools=["search", "read_file"],
        )

        assert skill.source_url == "https://github.com/org/repo"
        assert skill.body_content == "# SKILL.md\nDoes stuff."
        assert skill.files == ["main.py", "helper.py"]
        assert skill.license == "MIT"
        assert skill.compatibility == "python>=3.11"
        assert skill.metadata == {"version": "1.0", "author": "tester"}
        assert skill.allowed_tools == ["search", "read_file"]

    async def test_install_skill_optional_params_default_to_empty(
        self, mock_collection, mock_cache_invalidator
    ):
        """Optional list/dict params must default to empty containers, not None."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="bare-skill",
            description="Minimal skill",
            target="executor",
            vfs_path="/skills/bare-skill",
            source=SkillSource.INLINE,
        )

        assert skill.files == []
        assert skill.metadata == {}
        assert skill.allowed_tools == []
        assert skill.source_url is None
        assert skill.body_content is None
        assert skill.license is None
        assert skill.compatibility is None

    async def test_install_skill_returns_installed_skill(
        self, mock_collection, mock_cache_invalidator
    ):
        """install_skill must return a Skill with the correct field values."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="ret-skill",
            description="Return value test",
            target="gmail_agent",
            vfs_path="/skills/ret-skill",
            source=SkillSource.URL,
        )

        assert isinstance(skill, Skill)
        assert skill.user_id == "u1"
        assert skill.name == "ret-skill"
        assert skill.description == "Return value test"
        assert skill.target == "gmail_agent"
        assert skill.vfs_path == "/skills/ret-skill"
        assert skill.source == SkillSource.URL
        assert skill.enabled is True
        assert skill.id is not None

    async def test_install_skill_persists_to_db(
        self, mock_collection, mock_cache_invalidator
    ):
        """install_skill must call insert_one exactly once with the correct document."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        skill = await install_skill(
            user_id="u1",
            name="db-skill",
            description="DB persistence test",
            target="executor",
            vfs_path="/skills/db-skill",
            source=SkillSource.INLINE,
        )

        mock_collection.insert_one.assert_called_once()
        inserted_doc = mock_collection.insert_one.call_args[0][0]
        assert inserted_doc["_id"] == skill.id
        assert inserted_doc["user_id"] == "u1"
        assert inserted_doc["name"] == "db-skill"
        assert "id" not in inserted_doc

    async def test_install_skill_same_name_different_target_allowed(
        self, mock_collection, mock_cache_invalidator
    ):
        """The same skill name for a different target is NOT a duplicate."""
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock()

        # Both calls find no existing record — they are for different targets.
        skill_a = await install_skill(
            user_id="u1",
            name="shared-name",
            description="For executor",
            target="executor",
            vfs_path="/skills/shared-name",
            source=SkillSource.INLINE,
        )
        skill_b = await install_skill(
            user_id="u1",
            name="shared-name",
            description="For gmail_agent",
            target="gmail_agent",
            vfs_path="/skills/shared-name",
            source=SkillSource.INLINE,
        )

        assert skill_a.target == "executor"
        assert skill_b.target == "gmail_agent"
        assert mock_collection.insert_one.call_count == 2
