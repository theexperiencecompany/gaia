"""Unit tests for agent-skills Pydantic models and the skills API endpoints.

The production unit under test is ``app/agents/skills/models.py`` — the
validators, field constraints, defaults, serializer and the enum that back
every skill document. The endpoint tests exercise the same models through the
real FastAPI route contract (request parsing + response serialization).

Behavior spec
=============

UNIT: app/agents/skills/models.py :: _validate_skill_name
EXPECTED: Return the name unchanged when valid; raise ValueError with a precise
          message for empty / over-length / bad-pattern / consecutive-hyphen names.
MECHANISM: empty -> "name must not be empty"; len>64 -> "...at most 64 characters";
           pattern miss -> "...only lowercase letters, numbers, and hyphens...";
           "--" present -> "name must not contain consecutive hyphens"; else return value.
MUST-CATCH: each guard fires on its own input; the valid path returns the SAME
            string (not None); the >64 boundary is exclusive (64 passes, 65 fails);
            each error message is the documented one (return_none / message mutants).

UNIT: app/agents/skills/models.py :: _validate_skill_description
EXPECTED: Return the description when it has non-whitespace content; raise on
          empty or whitespace-only.
MECHANISM: ``if not value or not value.strip(): raise``; else return value.
MUST-CATCH: empty AND whitespace-only both rejected (the two `not` operands and
            the `or`); the valid path returns the SAME string (not None).

UNIT: app/agents/skills/models.py :: Skill
EXPECTED: Validate name/description via the shared validators; default target
          "executor", enabled True, installed_at tz-aware now, updated_at None;
          serialize installed_at/updated_at to ISO string or None; enforce the
          max_length field constraints; expose InstalledSkill as the same class.
MECHANISM: field_validator("name"/"description"); field_serializer dumps datetimes;
           Field(max_length=...) on name/description/compatibility.
MUST-CATCH: defaults are exactly those values; serialize_datetime returns
            isoformat for a datetime and None for None (the `if value` branch);
            compatibility >500 and description >1024 rejected; InstalledSkill is Skill.

UNIT: app/agents/skills/models.py :: SkillMetadata
EXPECTED: Parse external frontmatter; required name/description run the shared
          validators; optional fields default to None/[]/{} and target "executor".
MUST-CATCH: name/description validation is wired in; the documented defaults.

UNIT: app/agents/skills/models.py :: SkillInlineCreateRequest
EXPECTED: Carry name/description/instructions with target defaulting to "executor";
          name max 64, description max 1024 (NO name-pattern validator here).
MUST-CATCH: default target; the two max_length constraints at their boundary.

UNIT: app/agents/skills/models.py :: SkillListResponse
EXPECTED: Default to an empty skill list and total 0.

UNIT: app/agents/skills/models.py :: SkillSource
EXPECTED: Exactly the four documented install sources.

EQUIVALENT MUTANTS (allowed survivors, justified):
  - ``description=`` strings on Field(...) declarations are OpenAPI doc text with
    no runtime behavior; mutating them to "" changes only generated docs.
  - The ``str -> ''`` mutation on Skill's ``id``/``vfs_path``/``source`` etc.
    descriptions is likewise doc-only.

The endpoint suite below additionally proves the route wiring (status codes,
delegation arguments, error mapping) and re-exercises the models through real
request/response serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.agents.skills.models import (
    InstalledSkill,
    Skill,
    SkillInlineCreateRequest,
    SkillListResponse,
    SkillMetadata,
    SkillSource,
    _validate_skill_description,
    _validate_skill_name,
)

if TYPE_CHECKING:
    pass

BASE_URL = "/api/v1/skills"
DISCOVER_URL = f"{BASE_URL}/discover"
INSTALL_GITHUB_URL = f"{BASE_URL}/install/github"
INSTALL_INLINE_URL = f"{BASE_URL}/install/inline"

# Patch targets
_DISCOVER_SKILLS = "app.api.v1.endpoints.skills.discover_skills_from_repo"
_GET_SKILL_FROM_REPO = "app.api.v1.endpoints.skills.get_skill_from_repo"
_INSTALL_GITHUB = "app.api.v1.endpoints.skills.install_from_github"
_INSTALL_INLINE = "app.api.v1.endpoints.skills.install_from_inline"
_LIST_SKILLS = "app.api.v1.endpoints.skills.list_skills"
_GET_SKILL = "app.api.v1.endpoints.skills.get_skill"
_ENABLE_SKILL = "app.api.v1.endpoints.skills.enable_skill"
_DISABLE_SKILL = "app.api.v1.endpoints.skills.disable_skill"
_UNINSTALL_SKILL = "app.api.v1.endpoints.skills.uninstall_skill_full"


def _make_skill_mock(**overrides) -> Skill:
    base: dict[str, object] = {
        "id": "sk_abc123",
        "user_id": "507f1f77bcf86cd799439011",
        "name": "my-skill",
        "description": "A test skill",
        "target": "executor",
        "license": None,
        "compatibility": None,
        "metadata": {},
        "allowed_tools": [],
        "body_content": "# My Skill\nDo things.",
        "vfs_path": "/skills/my-skill",
        "enabled": True,
        "source": "github",
        "source_url": "https://github.com/org/repo",
        "installed_at": datetime(2025, 1, 1, tzinfo=UTC),
        "updated_at": None,
        "files": ["SKILL.md"],
    }
    base.update(overrides)
    return Skill(**base)  # type: ignore[arg-type]


def _make_discovered_skill(**overrides) -> MagicMock:
    base = {
        "name": "my-skill",
        "description": "Discovered skill",
        "path": "skills/my-skill",
    }
    base.update(overrides)
    mock = MagicMock()
    for k, v in base.items():
        setattr(mock, k, v)
    mock.to_dict = MagicMock(return_value=base)
    return mock


# ---------------------------------------------------------------------------
# models.py :: _validate_skill_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateSkillName:
    """Direct tests for the skill-name validator (the production unit)."""

    def test_valid_name_returned_unchanged(self):
        # The valid path must return the SAME value, not None or a constant.
        assert _validate_skill_name("my-skill") == "my-skill"
        assert _validate_skill_name("a1") == "a1"
        assert _validate_skill_name("a") == "a"

    def test_sixty_four_chars_is_the_inclusive_upper_bound(self):
        name = "a" * 64
        assert _validate_skill_name(name) == name

    def test_sixty_five_chars_rejected_with_length_message(self):
        with pytest.raises(ValueError, match="name must be at most 64 characters"):
            _validate_skill_name("a" * 65)

    def test_empty_name_rejected_with_empty_message(self):
        with pytest.raises(ValueError, match="name must not be empty"):
            _validate_skill_name("")

    def test_uppercase_rejected_with_pattern_message(self):
        with pytest.raises(
            ValueError,
            match="name must contain only lowercase letters, numbers, and hyphens",
        ):
            _validate_skill_name("BadName")

    def test_underscore_rejected_by_pattern(self):
        with pytest.raises(ValueError, match="lowercase letters, numbers, and hyphens"):
            _validate_skill_name("bad_name")

    def test_leading_hyphen_rejected_by_pattern(self):
        with pytest.raises(ValueError, match="must not start or end with a hyphen"):
            _validate_skill_name("-abc")

    def test_trailing_hyphen_rejected_by_pattern(self):
        with pytest.raises(ValueError, match="must not start or end with a hyphen"):
            _validate_skill_name("abc-")

    def test_consecutive_hyphens_rejected_with_specific_message(self):
        # Single internal hyphen is fine; doubled hyphens trip the dedicated guard.
        with pytest.raises(ValueError, match="name must not contain consecutive hyphens"):
            _validate_skill_name("a--b")


# ---------------------------------------------------------------------------
# models.py :: _validate_skill_description
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateSkillDescription:
    """Direct tests for the description validator (the production unit)."""

    def test_valid_description_returned_unchanged(self):
        assert _validate_skill_description("Does a useful thing") == "Does a useful thing"

    def test_description_with_surrounding_whitespace_kept_verbatim(self):
        # Non-empty after strip -> accepted and returned exactly as given.
        assert _validate_skill_description("  hi  ") == "  hi  "

    def test_empty_description_rejected(self):
        with pytest.raises(ValueError, match="description must not be empty"):
            _validate_skill_description("")

    def test_whitespace_only_description_rejected(self):
        # Catches the `not value.strip()` operand specifically (value is truthy here).
        with pytest.raises(ValueError, match="description must not be empty"):
            _validate_skill_description("   \t\n")


# ---------------------------------------------------------------------------
# models.py :: Skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillModel:
    """Field constraints, defaults, validators and serializer on Skill."""

    def test_defaults_when_only_required_fields_given(self):
        skill = Skill(
            user_id="u1", name="ok-skill", description="d", vfs_path="/p", source="inline"
        )
        assert skill.target == "executor"
        assert skill.enabled is True
        assert skill.updated_at is None
        assert skill.license is None
        assert skill.compatibility is None
        assert skill.metadata == {}
        assert skill.allowed_tools == []
        assert skill.files == []
        assert skill.id is None

    def test_installed_at_defaults_to_tz_aware_utc_now(self):
        before = datetime.now(UTC)
        skill = Skill(user_id="u1", name="ok", description="d", vfs_path="/p", source="inline")
        after = datetime.now(UTC)
        assert skill.installed_at.tzinfo is not None
        assert before <= skill.installed_at <= after

    def test_name_validator_is_wired_in(self):
        with pytest.raises(ValueError, match="consecutive hyphens"):
            Skill(user_id="u1", name="a--b", description="d", vfs_path="/p", source="inline")

    def test_description_validator_is_wired_in(self):
        with pytest.raises(ValueError, match="description must not be empty"):
            Skill(user_id="u1", name="ok", description="   ", vfs_path="/p", source="inline")

    def test_source_accepts_enum_values(self):
        skill = Skill(user_id="u1", name="ok", description="d", vfs_path="/p", source="github")
        assert skill.source is SkillSource.GITHUB

    def test_compatibility_max_length_500(self):
        ok = Skill(
            user_id="u1",
            name="ok",
            description="d",
            vfs_path="/p",
            source="inline",
            compatibility="c" * 500,
        )
        assert ok.compatibility == "c" * 500
        with pytest.raises(ValueError, match="at most 500 characters"):
            Skill(
                user_id="u1",
                name="ok",
                description="d",
                vfs_path="/p",
                source="inline",
                compatibility="c" * 501,
            )

    def test_description_max_length_1024(self):
        with pytest.raises(ValueError, match="at most 1024 characters"):
            Skill(
                user_id="u1",
                name="ok",
                description="d" * 1025,
                vfs_path="/p",
                source="inline",
            )

    def test_serialize_datetime_returns_isoformat_for_a_datetime(self):
        skill = _make_skill_mock(
            installed_at=datetime(2025, 1, 1, 12, 30, tzinfo=UTC),
            updated_at=datetime(2025, 6, 2, 9, 0, tzinfo=UTC),
        )
        dumped = skill.model_dump()
        assert dumped["installed_at"] == "2025-01-01T12:30:00+00:00"
        assert dumped["updated_at"] == "2025-06-02T09:00:00+00:00"

    def test_serialize_datetime_returns_none_for_none(self):
        # The falsy branch of `value.isoformat() if value else None`.
        skill = _make_skill_mock(updated_at=None)
        assert skill.model_dump()["updated_at"] is None

    def test_installed_skill_is_alias_of_skill(self):
        assert InstalledSkill is Skill


# ---------------------------------------------------------------------------
# models.py :: SkillMetadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillMetadata:
    """Frontmatter parsing model — shares the name/description validators."""

    def test_defaults_for_optional_fields(self):
        meta = SkillMetadata(name="my-skill", description="does things")
        assert meta.target == "executor"
        assert meta.license is None
        assert meta.compatibility is None
        assert meta.metadata == {}
        assert meta.allowed_tools == []

    def test_name_validator_is_wired_in(self):
        with pytest.raises(ValueError, match="consecutive hyphens"):
            SkillMetadata(name="a--b", description="d")

    def test_description_validator_is_wired_in(self):
        with pytest.raises(ValueError, match="description must not be empty"):
            SkillMetadata(name="ok", description="")

    def test_description_max_length_1024(self):
        # The description validator only rejects empties, so max_length is the
        # sole length guard on SkillMetadata.description.
        ok = SkillMetadata(name="ok", description="d" * 1024)
        assert len(ok.description) == 1024
        with pytest.raises(ValueError, match="at most 1024 characters"):
            SkillMetadata(name="ok", description="d" * 1025)

    def test_compatibility_max_length_500(self):
        ok = SkillMetadata(name="ok", description="d", compatibility="c" * 500)
        assert len(ok.compatibility) == 500
        with pytest.raises(ValueError, match="at most 500 characters"):
            SkillMetadata(name="ok", description="d", compatibility="c" * 501)


# ---------------------------------------------------------------------------
# models.py :: SkillInlineCreateRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillInlineCreateRequest:
    """Inline-create request — max_length guards but NO name-pattern validator."""

    def test_target_defaults_to_executor(self):
        req = SkillInlineCreateRequest(name="ok", description="d", instructions="body")
        assert req.target == "executor"

    def test_name_max_length_64(self):
        ok = SkillInlineCreateRequest(name="a" * 64, description="d", instructions="b")
        assert ok.name == "a" * 64
        with pytest.raises(ValueError, match="at most 64 characters"):
            SkillInlineCreateRequest(name="a" * 65, description="d", instructions="b")

    def test_description_max_length_1024(self):
        with pytest.raises(ValueError, match="at most 1024 characters"):
            SkillInlineCreateRequest(name="ok", description="d" * 1025, instructions="b")


# ---------------------------------------------------------------------------
# models.py :: SkillListResponse / SkillSource
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillListResponseAndSource:
    def test_list_response_defaults_to_empty(self):
        resp = SkillListResponse()
        assert resp.skills == []
        assert resp.total == 0

    def test_skill_source_members(self):
        assert SkillSource.GITHUB.value == "github"
        assert SkillSource.URL.value == "url"
        assert SkillSource.UPLOAD.value == "upload"
        assert SkillSource.INLINE.value == "inline"


# ---------------------------------------------------------------------------
# GET /skills/discover
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiscoverSkills:
    """Tests for the discover skills endpoint."""

    async def test_discover_skills_returns_200(self, client: AsyncClient):
        mock_skills = [_make_discovered_skill()]
        with patch(
            _DISCOVER_SKILLS,
            new_callable=AsyncMock,
            return_value=mock_skills,
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "owner/repo"})

        assert response.status_code == 200
        data = response.json()
        assert data["repo"] == "owner/repo"
        assert data["count"] == 1
        assert len(data["skills"]) == 1

    async def test_discover_skills_custom_branch(self, client: AsyncClient):
        with patch(
            _DISCOVER_SKILLS,
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_discover:
            response = await client.get(
                DISCOVER_URL,
                params={"repo": "owner/repo", "branch": "develop"},
            )

        assert response.status_code == 200
        mock_discover.assert_awaited_once_with("owner/repo", "develop")

    async def test_discover_skills_missing_repo_returns_422(self, client: AsyncClient):
        response = await client.get(DISCOVER_URL)
        assert response.status_code == 422

    async def test_discover_skills_invalid_repo_returns_400(self, client: AsyncClient):
        with patch(
            _DISCOVER_SKILLS,
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid repo format"),
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "bad-format"})

        assert response.status_code == 400

    async def test_discover_skills_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _DISCOVER_SKILLS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("GitHub API error"),
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "owner/repo"})

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /skills/install/github
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallFromGitHub:
    """Tests for the install skill from GitHub endpoint."""

    async def test_install_with_skill_path_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock()
        with patch(
            _INSTALL_GITHUB,
            new_callable=AsyncMock,
            return_value=mock_skill,
        ) as mock_install:
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 201
        # The explicit path is forwarded verbatim; the serialized skill comes back.
        mock_install.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011",
            repo_url="owner/repo",
            skill_path="skills/my-skill",
            target_override=None,
        )
        assert response.json()["name"] == "my-skill"

    async def test_install_with_skill_name_auto_discovers(self, client: AsyncClient):
        mock_discovered = _make_discovered_skill(path="skills/discovered-path")
        mock_skill = _make_skill_mock()
        with (
            patch(
                _GET_SKILL_FROM_REPO,
                new_callable=AsyncMock,
                return_value=mock_discovered,
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_install,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "my-skill"},
            )

        assert response.status_code == 201
        # The discovered .path must be the one passed to the installer.
        assert mock_install.await_args.kwargs["skill_path"] == "skills/discovered-path"

    async def test_install_skill_not_found_returns_404(self, client: AsyncClient):
        with patch(
            _GET_SKILL_FROM_REPO,
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "nonexistent"},
            )

        assert response.status_code == 404

    async def test_install_no_path_or_name_returns_400(self, client: AsyncClient):
        response = await client.post(
            INSTALL_GITHUB_URL,
            params={"repo_url": "owner/repo"},
        )
        assert response.status_code == 400

    async def test_install_missing_repo_url_returns_422(self, client: AsyncClient):
        response = await client.post(INSTALL_GITHUB_URL)
        assert response.status_code == 422

    async def test_install_value_error_returns_400(self, client: AsyncClient):
        with patch(
            _INSTALL_GITHUB,
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid skill format"),
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/bad",
                },
            )

        assert response.status_code == 400

    async def test_install_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _INSTALL_GITHUB,
            new_callable=AsyncMock,
            side_effect=RuntimeError("GitHub API rate limited"),
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /skills/install/inline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallInline:
    """Tests for the create inline skill endpoint."""

    async def test_create_inline_skill_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock(source="inline")
        with patch(
            _INSTALL_INLINE,
            new_callable=AsyncMock,
            return_value=mock_skill,
        ) as mock_inline:
            response = await client.post(
                INSTALL_INLINE_URL,
                json={
                    "name": "my-skill",
                    "description": "Does something useful",
                    "instructions": "# Instructions\nDo the thing.",
                    "target": "gmail_agent",
                },
            )

        assert response.status_code == 201
        # Body fields are forwarded to the installer, not constants.
        mock_inline.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011",
            name="my-skill",
            description="Does something useful",
            instructions="# Instructions\nDo the thing.",
            target="gmail_agent",
        )

    async def test_create_inline_skill_missing_name_returns_422(self, client: AsyncClient):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "description": "Does something",
                "instructions": "Do the thing.",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_missing_description_returns_422(self, client: AsyncClient):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "name": "my-skill",
                "instructions": "Do the thing.",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_missing_instructions_returns_422(self, client: AsyncClient):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "name": "my-skill",
                "description": "Does something useful",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_value_error_returns_400(self, client: AsyncClient):
        with patch(
            _INSTALL_INLINE,
            new_callable=AsyncMock,
            side_effect=ValueError("Duplicate skill name"),
        ):
            response = await client.post(
                INSTALL_INLINE_URL,
                json={
                    "name": "my-skill",
                    "description": "Does something useful",
                    "instructions": "Do the thing.",
                },
            )

        assert response.status_code == 400

    async def test_create_inline_skill_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _INSTALL_INLINE,
            new_callable=AsyncMock,
            side_effect=RuntimeError("VFS error"),
        ):
            response = await client.post(
                INSTALL_INLINE_URL,
                json={
                    "name": "my-skill",
                    "description": "Does something useful",
                    "instructions": "Do the thing.",
                },
            )

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListSkills:
    """Tests for the list skills endpoint."""

    async def test_list_skills_returns_200(self, client: AsyncClient):
        mock_skills = [_make_skill_mock(), _make_skill_mock(name="second-skill")]
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            return_value=mock_skills,
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        # total reflects the actual count of returned skills, not a constant.
        assert data["total"] == 2
        assert len(data["skills"]) == 2
        assert {s["name"] for s in data["skills"]} == {"my-skill", "second-skill"}

    async def test_list_skills_empty(self, client: AsyncClient):
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["skills"] == []

    async def test_list_skills_with_target_filter(self, client: AsyncClient):
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_list:
            await client.get(BASE_URL, params={"target": "gmail_agent"})

        mock_list.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011",
            target="gmail_agent",
            enabled_only=False,
        )

    async def test_list_skills_enabled_only(self, client: AsyncClient):
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_list:
            await client.get(BASE_URL, params={"enabled_only": "true"})

        mock_list.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011",
            target=None,
            enabled_only=True,
        )

    async def test_list_skills_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /skills/{skill_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSkill:
    """Tests for the get skill by ID endpoint."""

    async def test_get_skill_returns_200(self, client: AsyncClient):
        mock_skill = _make_skill_mock()
        with patch(
            _GET_SKILL,
            new_callable=AsyncMock,
            return_value=mock_skill,
        ) as mock_get:
            response = await client.get(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 200
        mock_get.assert_awaited_once_with("507f1f77bcf86cd799439011", "sk_abc123")
        assert response.json()["name"] == "my-skill"

    async def test_get_skill_not_found_returns_404(self, client: AsyncClient):
        with patch(
            _GET_SKILL,
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.get(f"{BASE_URL}/sk_nonexistent")

        assert response.status_code == 404

    async def test_get_skill_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _GET_SKILL,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PATCH /skills/{skill_id}/enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnableSkill:
    """Tests for the enable skill endpoint."""

    async def test_enable_skill_returns_200(self, client: AsyncClient):
        with patch(
            _ENABLE_SKILL,
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/enable")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["enabled"] is True
        assert data["skill_id"] == "sk_abc123"

    async def test_enable_skill_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _ENABLE_SKILL,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/enable")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# PATCH /skills/{skill_id}/disable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDisableSkill:
    """Tests for the disable skill endpoint."""

    async def test_disable_skill_returns_200(self, client: AsyncClient):
        with patch(
            _DISABLE_SKILL,
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/disable")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["enabled"] is False
        assert data["skill_id"] == "sk_abc123"

    async def test_disable_skill_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _DISABLE_SKILL,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/disable")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /skills/{skill_id}
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUninstallSkill:
    """Tests for the uninstall skill endpoint."""

    async def test_uninstall_skill_returns_204(self, client: AsyncClient):
        with patch(
            _UNINSTALL_SKILL,
            new_callable=AsyncMock,
            return_value=True,
        ):
            response = await client.delete(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 204

    async def test_uninstall_skill_not_found_returns_404(self, client: AsyncClient):
        with patch(
            _UNINSTALL_SKILL,
            new_callable=AsyncMock,
            return_value=False,
        ):
            response = await client.delete(f"{BASE_URL}/sk_nonexistent")

        assert response.status_code == 404

    async def test_uninstall_skill_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _UNINSTALL_SKILL,
            new_callable=AsyncMock,
            side_effect=RuntimeError("VFS error"),
        ):
            response = await client.delete(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 500
