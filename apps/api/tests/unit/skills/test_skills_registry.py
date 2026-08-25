"""Unit tests for the skills registry CRUD operations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest

from app.agents.skills.models import (
    Skill,
    SkillMetadata,
    SkillSource,
    _validate_skill_description,
    _validate_skill_name,
)
from app.agents.skills.registry import (
    SkillInstallRequest,
    disable_skill,
    enable_skill,
    get_skill,
    get_skill_by_name,
    get_skills_for_agent,
    install_skill,
    list_skills,
    uninstall_skill,
)
from app.utils.errors import AppError


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
        installed_at=datetime(2024, 1, 1, tzinfo=UTC),
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


class TestSkillDescriptionValidation:
    def test_valid_description(self):
        assert _validate_skill_description("Does something useful") == "Does something useful"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_skill_description("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_skill_description("   ")


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


class TestSkillSource:
    def test_all_sources(self):
        assert SkillSource.GITHUB.value == "github"
        assert SkillSource.URL.value == "url"
        assert SkillSource.UPLOAD.value == "upload"
        assert SkillSource.INLINE.value == "inline"


def _skill(**overrides: object) -> Skill:
    data: dict = dict(
        id="s1",
        user_id="u1",
        name="test",
        description="Test skill",
        target="executor",
        vfs_path="/skills/test",
        source=SkillSource.GITHUB,
        enabled=True,
        installed_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    data.update(overrides)
    return Skill(**data)


def _request(**overrides: object) -> SkillInstallRequest:
    data: dict = dict(
        user_id="u1",
        name="my-skill",
        description="Does something useful",
        target="executor",
        vfs_path="/skills/my-skill",
        source=SkillSource.INLINE,
    )
    data.update(overrides)
    return SkillInstallRequest(**data)


@pytest.fixture
def mock_skill_repo():
    with patch("app.agents.skills.registry.skill_repository") as repo:
        yield repo


class TestSkillRegistryCRUD:
    """The registry delegates to SkillsRepository; mock that seam."""

    async def test_get_skill_found(self, mock_skill_repo):
        mock_skill_repo.get_for_user = AsyncMock(return_value=_skill(id="s1", name="test"))
        skill = await get_skill("u1", "s1")
        assert skill is not None and skill.id == "s1"
        mock_skill_repo.get_for_user.assert_awaited_once_with("s1", "u1")

    async def test_get_skill_not_found(self, mock_skill_repo):
        mock_skill_repo.get_for_user = AsyncMock(return_value=None)
        assert await get_skill("u1", "missing") is None

    async def test_uninstall_success(self, mock_skill_repo):
        mock_skill_repo.delete_for_user = AsyncMock(return_value=True)
        assert await uninstall_skill(user_id="u1", skill_id="s1") is True

    async def test_uninstall_not_found(self, mock_skill_repo):
        mock_skill_repo.delete_for_user = AsyncMock(return_value=False)
        assert await uninstall_skill(user_id="u1", skill_id="missing") is False

    async def test_enable_skill(self, mock_skill_repo):
        mock_skill_repo.set_enabled = AsyncMock(return_value=True)
        assert await enable_skill(user_id="test_user", skill_id="s1") is True
        mock_skill_repo.set_enabled.assert_awaited_once_with("test_user", "s1", True)

    async def test_disable_skill(self, mock_skill_repo):
        mock_skill_repo.set_enabled = AsyncMock(return_value=True)
        assert await disable_skill(user_id="test_user", skill_id="s1") is True
        mock_skill_repo.set_enabled.assert_awaited_once_with("test_user", "s1", False)

    async def test_enable_skill_not_found(self, mock_skill_repo):
        mock_skill_repo.set_enabled = AsyncMock(return_value=False)
        assert await enable_skill(user_id="u1", skill_id="missing") is False

    async def test_list_skills(self, mock_skill_repo):
        mock_skill_repo.list_for_user = AsyncMock(
            return_value=[_skill(id=f"s{i}") for i in range(3)]
        )
        skills = await list_skills("u1")
        assert len(skills) == 3 and all(isinstance(s, Skill) for s in skills)

    async def test_list_skills_with_filters(self, mock_skill_repo):
        mock_skill_repo.list_for_user = AsyncMock(return_value=[])
        await list_skills("u1", target="gmail_agent", enabled_only=True)
        call = mock_skill_repo.list_for_user.await_args
        assert call.args[0] == "u1"
        assert call.kwargs["target"] == "gmail_agent"
        assert call.kwargs["enabled_only"] is True

    async def test_get_skill_by_name(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=_skill(name="my-skill"))
        skill = await get_skill_by_name("u1", "my-skill")
        assert skill is not None and skill.name == "my-skill"

    async def test_get_skill_by_name_with_target(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        await get_skill_by_name("u1", "my-skill", target="gmail_agent")
        mock_skill_repo.find_by_name.assert_awaited_once_with("u1", "my-skill", "gmail_agent")


class TestGetSkillsForAgent:
    """get_skills_for_agent — the cached path, delegating to repo.for_agent."""

    @pytest.fixture(autouse=True)
    def bypass_cache(self):
        with (
            patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            yield

    async def test_delegates_to_repo_for_agent(self, mock_skill_repo):
        mock_skill_repo.for_agent = AsyncMock(return_value=[])
        await get_skills_for_agent(user_id="u1", agent_name="executor")
        mock_skill_repo.for_agent.assert_awaited_once_with("u1", "executor")

    async def test_returns_repo_skills(self, mock_skill_repo):
        mock_skill_repo.for_agent = AsyncMock(
            return_value=[_skill(id="s1"), _skill(id="s2", user_id="system")]
        )
        skills = await get_skills_for_agent(user_id="u1", agent_name="executor")
        assert len(skills) == 2 and all(isinstance(s, Skill) for s in skills)

    async def test_cache_hit_returns_without_repo_call(self, mock_skill_repo):
        mock_skill_repo.for_agent = AsyncMock()
        cached = [_skill(id="s1", name="cached-skill")]
        with patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=cached):
            result = await get_skills_for_agent(user_id="u1", agent_name="executor")
        mock_skill_repo.for_agent.assert_not_awaited()
        assert result == cached


class TestInstallSkill:
    """install_skill — duplicate guard, created Skill shape, return value."""

    @pytest.fixture(autouse=True)
    def bypass_cache_invalidation(self):
        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as delete_mock:
            yield delete_mock

    async def test_invalidates_user_skill_caches_with_request_user_id(
        self, mock_skill_repo, bypass_cache_invalidation
    ):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        mock_skill_repo.create = AsyncMock()
        await install_skill(_request())
        invalidated = [call.args[0] for call in bypass_cache_invalidation.await_args_list]
        assert "skills:user:u1:agent:*" in invalidated
        assert "skills:text:v2:u1:*" in invalidated

    async def test_stamps_install_context_on_wide_event(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        mock_skill_repo.create = AsyncMock()
        with patch("app.agents.skills.registry.log") as mock_log:
            await install_skill(_request(name="my-skill"))
        mock_log.set.assert_called_once_with(
            user_id="u1",
            skill={"operation": "install", "skill_name": "my-skill"},
        )

    async def test_checks_duplicate_by_user_name_and_target(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        mock_skill_repo.create = AsyncMock()
        await install_skill(_request(user_id="u1", name="my-skill", target="gmail_agent"))
        mock_skill_repo.find_by_name.assert_awaited_once_with("u1", "my-skill", "gmail_agent")

    async def test_creates_skill_with_uuid_id(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        mock_skill_repo.create = AsyncMock()
        await install_skill(_request(source=SkillSource.GITHUB))
        mock_skill_repo.create.assert_awaited_once()
        created = mock_skill_repo.create.await_args.args[0]
        assert isinstance(created, Skill)
        assert created.user_id == "u1" and created.name == "my-skill"
        assert created.source is SkillSource.GITHUB and created.enabled is True
        assert created.id  # UUID assigned

    async def test_returns_installed_skill(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=None)
        mock_skill_repo.create = AsyncMock()
        skill = await install_skill(
            SkillInstallRequest(
                user_id="u1",
                name="my-skill",
                description="Does something useful",
                target="executor",
                vfs_path="/skills/my-skill",
                source=SkillSource.INLINE,
            )
        )
        assert isinstance(skill, Skill)
        assert skill.user_id == "u1" and skill.enabled is True and skill.id

    async def test_raises_on_duplicate(self, mock_skill_repo):
        mock_skill_repo.find_by_name = AsyncMock(return_value=_skill(name="my-skill"))
        mock_skill_repo.create = AsyncMock()
        with pytest.raises(AppError, match="already installed") as exc_info:
            await install_skill(_request())
        assert exc_info.value.status_code == 409
        assert exc_info.value.why == "Skill names are unique per user and target."
        assert (
            exc_info.value.fix
            == "Uninstall the existing skill first, or install under a different name."
        )
        mock_skill_repo.create.assert_not_awaited()
