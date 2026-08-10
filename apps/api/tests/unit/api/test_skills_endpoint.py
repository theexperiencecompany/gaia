"""Unit tests for the skills API endpoints.

Tests cover:
- GET    /api/v1/skills/discover
- POST   /api/v1/skills/install/github
- POST   /api/v1/skills/install/inline
- PUT    /api/v1/skills/{skill_id}
- GET    /api/v1/skills
- GET    /api/v1/skills/{skill_id}
- PATCH  /api/v1/skills/{skill_id}/enable
- PATCH  /api/v1/skills/{skill_id}/disable
- DELETE /api/v1/skills/{skill_id}
- GET    /api/v1/skills/targets
- GET    /api/v1/skills/builtin

Every handler's service seam is mocked (never the handler itself), and each
test asserts the exact response shape, the exact arguments the handler passes
to the mocked service, and the exact wide-event log calls the handler emits —
so a wrong status, detail, payload, service call, or log field fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, call, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.agents.skills.github_discovery import DiscoveredSkill
from app.agents.skills.models import Skill, SkillTarget
from app.api.v1.endpoints.skills import _get_user_id
from app.constants.log_tags import LogTag

BASE_URL = "/api/v1/skills"
DISCOVER_URL = f"{BASE_URL}/discover"
INSTALL_GITHUB_URL = f"{BASE_URL}/install/github"
INSTALL_INLINE_URL = f"{BASE_URL}/install/inline"

USER_ID = "507f1f77bcf86cd799439011"

# Patch targets
_LOG = "app.api.v1.endpoints.skills.log"
_DISCOVER_SKILLS = "app.api.v1.endpoints.skills.discover_skills_from_repo"
_GET_SKILL_FROM_REPO = "app.api.v1.endpoints.skills.get_skill_from_repo"
_INSTALL_GITHUB = "app.api.v1.endpoints.skills.install_from_github"
_INSTALL_INLINE = "app.api.v1.endpoints.skills.install_from_inline"
_LIST_SKILLS = "app.api.v1.endpoints.skills.list_skills"
_GET_SKILL = "app.api.v1.endpoints.skills.get_skill"
_ENABLE_SKILL = "app.api.v1.endpoints.skills.enable_skill"
_DISABLE_SKILL = "app.api.v1.endpoints.skills.disable_skill"
_UNINSTALL_SKILL = "app.api.v1.endpoints.skills.uninstall_skill_full"
_GET_SKILL_TARGETS = "app.api.v1.endpoints.skills.get_skill_targets"
_GET_CONNECTED_INTEGRATION_IDS = "app.agents.skills.targets.get_connected_integration_ids"
_LOAD_BUILTIN_SKILLS = "app.api.v1.endpoints.skills.load_builtin_skills"
_GET_CONNECTED_INTEGRATION_IDS_ENDPOINT = (
    "app.api.v1.endpoints.skills.get_connected_integration_ids"
)
_UPDATE_SKILL_INLINE = "app.api.v1.endpoints.skills.update_skill_inline"

EXECUTOR_TARGET = SkillTarget(
    value="executor", label="General assistant", icon="executor", connected=True
)


def _make_skill_mock(**overrides) -> Skill:
    base: dict[str, Any] = {
        "id": "sk_abc123",
        "user_id": USER_ID,
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
    return Skill(**base)


def _make_discovered_skill(**overrides) -> DiscoveredSkill:
    base: dict[str, Any] = {
        "name": "my-skill",
        "description": "Discovered skill",
        "path": "skills/my-skill",
        "repo_url": "https://github.com/owner/repo",
        "subagent_id": "executor",
    }
    base.update(overrides)
    return DiscoveredSkill(**base)


# ---------------------------------------------------------------------------
# _get_user_id (dependency helper)
# ---------------------------------------------------------------------------


class TestGetUserId:
    """_get_user_id: extract the user id or fail the request with 401."""

    def test_returns_user_id_when_present(self) -> None:
        assert _get_user_id({"user_id": USER_ID}) == USER_ID

    def test_missing_user_id_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _get_user_id({})
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User not authenticated"

    def test_empty_user_id_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _get_user_id({"user_id": ""})
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "User not authenticated"


# ---------------------------------------------------------------------------
# GET /skills/discover
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    """Tests for the discover skills endpoint."""

    async def test_discover_skills_returns_200(self, client: AsyncClient):
        mock_skills = [_make_discovered_skill()]
        with (
            patch(
                _DISCOVER_SKILLS,
                new_callable=AsyncMock,
                return_value=mock_skills,
            ) as mock_discover,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "owner/repo"})

        assert response.status_code == 200
        assert response.json() == {
            "repo": "owner/repo",
            "branch": "main",
            "skills": [
                {
                    "name": "my-skill",
                    "description": "Discovered skill",
                    "path": "skills/my-skill",
                    "repo_url": "https://github.com/owner/repo",
                    "subagent_id": "executor",
                }
            ],
            "count": 1,
        }
        mock_discover.assert_awaited_once_with("owner/repo", "main")
        assert mock_log.set.call_args_list == [
            call(operation="discover_skills", skill_name="owner/repo"),
            call(result_count=1),
            call(outcome="success"),
        ]

    async def test_discover_skills_custom_branch(self, client: AsyncClient):
        with (
            patch(
                _DISCOVER_SKILLS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_discover,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(
                DISCOVER_URL,
                params={"repo": "owner/repo", "branch": "develop"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "repo": "owner/repo",
            "branch": "develop",
            "skills": [],
            "count": 0,
        }
        mock_discover.assert_awaited_once_with("owner/repo", "develop")
        assert mock_log.set.call_args_list == [
            call(operation="discover_skills", skill_name="owner/repo"),
            call(result_count=0),
            call(outcome="success"),
        ]

    async def test_discover_skills_missing_repo_returns_422(self, client: AsyncClient):
        response = await client.get(DISCOVER_URL)
        assert response.status_code == 422

    async def test_discover_skills_invalid_repo_returns_400(self, client: AsyncClient):
        with (
            patch(
                _DISCOVER_SKILLS,
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid repo format"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "bad-format"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid repo format"
        assert mock_log.set.call_args_list == [
            call(operation="discover_skills", skill_name="bad-format")
        ]
        mock_log.error.assert_not_called()

    async def test_discover_skills_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _DISCOVER_SKILLS,
                new_callable=AsyncMock,
                side_effect=RuntimeError("GitHub API error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(DISCOVER_URL, params={"repo": "owner/repo"})

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to discover skills from repository"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error discovering skills from repo",
            repo="owner/repo",
            error_type="RuntimeError",
            error="GitHub API error",
        )


# ---------------------------------------------------------------------------
# POST /skills/install/github
# ---------------------------------------------------------------------------


class TestInstallFromGitHub:
    """Tests for the install skill from GitHub endpoint."""

    async def test_install_with_skill_path_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock()
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_targets,
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 201
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_install.assert_awaited_once_with(
            user_id=USER_ID,
            repo_url="owner/repo",
            skill_path="skills/my-skill",
            target_override=None,
            allowed_targets=set(),
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                skill={"repo": "owner/repo", "name": None, "path": "skills/my-skill"},
            ),
            call(skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_install_with_skill_name_auto_discovers(self, client: AsyncClient):
        mock_discovered = _make_discovered_skill(path="skills/my-skill")
        mock_skill = _make_skill_mock()
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_targets,
            patch(
                _GET_SKILL_FROM_REPO,
                new_callable=AsyncMock,
                return_value=mock_discovered,
            ) as mock_discover,
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "my-skill"},
            )

        assert response.status_code == 201
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_discover.assert_awaited_once_with("owner/repo", "my-skill")
        mock_install.assert_awaited_once_with(
            user_id=USER_ID,
            repo_url="owner/repo",
            skill_path="skills/my-skill",
            target_override=None,
            allowed_targets=set(),
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                skill={"repo": "owner/repo", "name": "my-skill", "path": None},
            ),
            call(skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_install_with_target_override_passes_it_through(self, client: AsyncClient):
        mock_skill = _make_skill_mock()
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_targets,
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                    "target": "gmail_agent",
                },
            )

        assert response.status_code == 201
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_install.assert_awaited_once_with(
            user_id=USER_ID,
            repo_url="owner/repo",
            skill_path="skills/my-skill",
            target_override="gmail_agent",
            allowed_targets=set(),
        )
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                skill={
                    "repo": "owner/repo",
                    "name": None,
                    "path": "skills/my-skill",
                },
            ),
            call(skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_install_skill_not_found_returns_404(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _GET_SKILL_FROM_REPO,
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_discover,
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "nonexistent"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Skill 'nonexistent' not found in repository"
        mock_discover.assert_awaited_once_with("owner/repo", "nonexistent")
        mock_install.assert_not_awaited()
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                skill={"repo": "owner/repo", "name": "nonexistent", "path": None},
            )
        ]

    async def test_install_no_path_or_name_returns_400(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Either skill_path or skill_name must be provided"
        mock_install.assert_not_awaited()
        assert mock_log.set.call_args_list == [
            call(
                user={"id": USER_ID},
                skill={"repo": "owner/repo", "name": None, "path": None},
            )
        ]
        mock_log.error.assert_not_called()

    async def test_install_missing_repo_url_returns_422(self, client: AsyncClient):
        response = await client.post(INSTALL_GITHUB_URL)
        assert response.status_code == 422

    async def test_install_value_error_returns_400(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid skill format"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/bad",
                },
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid skill format"
        mock_log.error.assert_not_called()

    async def test_install_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                side_effect=RuntimeError("GitHub API rate limited"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to install skill from GitHub"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error installing skill from GitHub",
            user_id=USER_ID,
            repo="owner/repo",
            error_type="RuntimeError",
            error="GitHub API rate limited",
        )


# ---------------------------------------------------------------------------
# POST /skills/install/inline
# ---------------------------------------------------------------------------


class TestInstallInline:
    """Tests for the create inline skill endpoint. _validate_target runs for
    real here (only get_skill_targets, its I/O seam, is mocked)."""

    async def test_create_inline_skill_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock(source="inline")
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[EXECUTOR_TARGET],
            ) as mock_targets,
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_INLINE_URL,
                json={
                    "name": "my-skill",
                    "description": "Does something useful",
                    "instructions": "# Instructions\nDo the thing.",
                    "target": "executor",
                },
            )

        assert response.status_code == 201
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_install.assert_awaited_once_with(
            user_id=USER_ID,
            name="my-skill",
            description="Does something useful",
            instructions="# Instructions\nDo the thing.",
            target="executor",
        )
        assert mock_log.set.call_args_list == [
            call(user={"id": USER_ID}, skill={"name": "my-skill", "target": "executor"}),
            call(skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_create_inline_skill_disallowed_target_returns_400(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[EXECUTOR_TARGET],
            ) as mock_targets,
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
            ) as mock_install,
            patch(_LOG) as mock_log,
        ):
            response = await client.post(
                INSTALL_INLINE_URL,
                json={
                    "name": "my-skill",
                    "description": "Does something useful",
                    "instructions": "Do the thing.",
                    "target": "an-unconnected-integration",
                },
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Target 'an-unconnected-integration' is not available. "
            "Connect the integration before scoping a skill to it."
        )
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_install.assert_not_awaited()
        mock_log.error.assert_not_called()

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
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[EXECUTOR_TARGET],
            ),
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
                side_effect=ValueError("Duplicate skill name"),
            ),
            patch(_LOG) as mock_log,
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
        assert response.json()["detail"] == "Duplicate skill name"
        mock_log.error.assert_not_called()

    async def test_create_inline_skill_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[EXECUTOR_TARGET],
            ),
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
                side_effect=RuntimeError("VFS error"),
            ),
            patch(_LOG) as mock_log,
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
        assert response.json()["detail"] == "Failed to create skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error creating inline skill",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="VFS error",
        )


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


class TestListSkills:
    """Tests for the list skills endpoint."""

    async def test_list_skills_returns_200(self, client: AsyncClient):
        mock_skills = [_make_skill_mock()]
        with (
            patch(
                _LIST_SKILLS,
                new_callable=AsyncMock,
                return_value=mock_skills,
            ) as mock_list,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        assert response.json() == {
            "skills": [mock_skills[0].model_dump(mode="json")],
            "total": 1,
        }
        mock_list.assert_awaited_once_with(user_id=USER_ID, target=None, enabled_only=False)
        assert mock_log.set.call_args_list == [
            call(operation="list_skills"),
            call(result_count=1),
            call(outcome="success"),
        ]

    async def test_list_skills_empty(self, client: AsyncClient):
        with (
            patch(
                _LIST_SKILLS,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        assert response.json() == {"skills": [], "total": 0}
        assert mock_log.set.call_args_list == [
            call(operation="list_skills"),
            call(result_count=0),
            call(outcome="success"),
        ]

    async def test_list_skills_with_target_filter(self, client: AsyncClient):
        with (
            patch(
                _LIST_SKILLS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_list,
            patch(_LOG) as mock_log,
        ):
            await client.get(BASE_URL, params={"target": "gmail_agent"})

        mock_list.assert_awaited_once_with(
            user_id=USER_ID,
            target="gmail_agent",
            enabled_only=False,
        )
        assert mock_log.set.call_args_list == [
            call(operation="list_skills"),
            call(result_count=0),
            call(outcome="success"),
        ]

    async def test_list_skills_enabled_only(self, client: AsyncClient):
        with (
            patch(
                _LIST_SKILLS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_list,
            patch(_LOG) as mock_log,
        ):
            await client.get(BASE_URL, params={"enabled_only": "true"})

        mock_list.assert_awaited_once_with(
            user_id=USER_ID,
            target=None,
            enabled_only=True,
        )
        assert mock_log.set.call_args_list == [
            call(operation="list_skills"),
            call(result_count=0),
            call(outcome="success"),
        ]

    async def test_list_skills_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _LIST_SKILLS,
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to list skills"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error listing skills",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# GET /skills/{skill_id}
# ---------------------------------------------------------------------------


class TestGetSkill:
    """Tests for the get skill by ID endpoint."""

    async def test_get_skill_returns_200(self, client: AsyncClient):
        mock_skill = _make_skill_mock()
        with (
            patch(
                _GET_SKILL,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_get,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 200
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_get.assert_awaited_once_with(USER_ID, "sk_abc123")
        assert mock_log.set.call_args_list == [
            call(operation="get_skill", skill_id="sk_abc123"),
            call(skill_name="my-skill"),
            call(outcome="success"),
        ]

    async def test_get_skill_not_found_returns_404(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL,
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_get,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/sk_nonexistent")

        assert response.status_code == 404
        assert response.json()["detail"] == "Skill sk_nonexistent not found"
        mock_get.assert_awaited_once_with(USER_ID, "sk_nonexistent")
        assert mock_log.set.call_args_list == [
            call(operation="get_skill", skill_id="sk_nonexistent")
        ]

    async def test_get_skill_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL,
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to retrieve skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error getting skill",
            user_id=USER_ID,
            skill_id="sk_abc123",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# PATCH /skills/{skill_id}/enable
# ---------------------------------------------------------------------------


class TestEnableSkill:
    """Tests for the enable skill endpoint."""

    async def test_enable_skill_returns_200(self, client: AsyncClient):
        with (
            patch(
                _ENABLE_SKILL,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_enable,
            patch(_LOG) as mock_log,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/enable")

        assert response.status_code == 200
        assert response.json() == {"success": True, "skill_id": "sk_abc123", "enabled": True}
        mock_enable.assert_awaited_once_with(USER_ID, "sk_abc123")
        assert mock_log.set.call_args_list == [
            call(operation="enable_skill", skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_enable_skill_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _ENABLE_SKILL,
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/enable")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to enable skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error enabling skill",
            user_id=USER_ID,
            skill_id="sk_abc123",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# PATCH /skills/{skill_id}/disable
# ---------------------------------------------------------------------------


class TestDisableSkill:
    """Tests for the disable skill endpoint."""

    async def test_disable_skill_returns_200(self, client: AsyncClient):
        with (
            patch(
                _DISABLE_SKILL,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_disable,
            patch(_LOG) as mock_log,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/disable")

        assert response.status_code == 200
        assert response.json() == {"success": True, "skill_id": "sk_abc123", "enabled": False}
        mock_disable.assert_awaited_once_with(USER_ID, "sk_abc123")
        assert mock_log.set.call_args_list == [
            call(operation="disable_skill", skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_disable_skill_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _DISABLE_SKILL,
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.patch(f"{BASE_URL}/sk_abc123/disable")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to disable skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error disabling skill",
            user_id=USER_ID,
            skill_id="sk_abc123",
            error_type="RuntimeError",
            error="DB error",
        )


# ---------------------------------------------------------------------------
# DELETE /skills/{skill_id}
# ---------------------------------------------------------------------------


class TestUninstallSkill:
    """Tests for the uninstall skill endpoint."""

    async def test_uninstall_skill_returns_204(self, client: AsyncClient):
        with (
            patch(
                _UNINSTALL_SKILL,
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_uninstall,
            patch(_LOG) as mock_log,
        ):
            response = await client.delete(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 204
        assert response.content == b""
        mock_uninstall.assert_awaited_once_with(USER_ID, "sk_abc123")
        assert mock_log.set.call_args_list == [
            call(operation="uninstall_skill", skill_id="sk_abc123"),
            call(outcome="success"),
        ]

    async def test_uninstall_skill_not_found_returns_404(self, client: AsyncClient):
        with (
            patch(
                _UNINSTALL_SKILL,
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_uninstall,
            patch(_LOG) as mock_log,
        ):
            response = await client.delete(f"{BASE_URL}/sk_nonexistent")

        assert response.status_code == 404
        assert response.json()["detail"] == "Skill sk_nonexistent not found"
        mock_uninstall.assert_awaited_once_with(USER_ID, "sk_nonexistent")
        assert mock_log.set.call_args_list == [
            call(operation="uninstall_skill", skill_id="sk_nonexistent")
        ]

    async def test_uninstall_skill_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _UNINSTALL_SKILL,
                new_callable=AsyncMock,
                side_effect=RuntimeError("VFS error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.delete(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to uninstall skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error uninstalling skill",
            user_id=USER_ID,
            skill_id="sk_abc123",
            error_type="RuntimeError",
            error="VFS error",
        )


# ---------------------------------------------------------------------------
# GET /skills/targets
# ---------------------------------------------------------------------------


class TestListSkillTargets:
    """Tests for the skill-targets endpoint. Mocks only get_connected_integration_ids
    (the true I/O boundary) so get_skill_targets' own executor+connected-subagent
    assembly logic runs for real."""

    async def test_returns_executor_plus_connected_integration(self, client: AsyncClient):
        with (
            patch(
                _GET_CONNECTED_INTEGRATION_IDS,
                new_callable=AsyncMock,
                return_value=["gmail"],
            ) as mock_connected,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        assert response.json() == {
            "targets": [
                {
                    "value": "executor",
                    "label": "General assistant",
                    "icon": "executor",
                    "connected": True,
                },
                {
                    "value": "gmail_agent",
                    "label": "Gmail",
                    "icon": "gmail",
                    "connected": True,
                },
            ]
        }
        mock_connected.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(operation="list_skill_targets"),
            call(result_count=2, outcome="success"),
        ]

    async def test_no_connected_integrations_returns_executor_only(self, client: AsyncClient):
        with (
            patch(
                _GET_CONNECTED_INTEGRATION_IDS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_connected,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        assert response.json() == {
            "targets": [
                {
                    "value": "executor",
                    "label": "General assistant",
                    "icon": "executor",
                    "connected": True,
                }
            ]
        }
        mock_connected.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(operation="list_skill_targets"),
            call(result_count=1, outcome="success"),
        ]

    async def test_unknown_connected_integration_id_is_skipped(self, client: AsyncClient):
        """An id with no subagent registration (or no subagent config) must be
        skipped, not surfaced as a broken/blank target the UI can select."""
        with (
            patch(
                _GET_CONNECTED_INTEGRATION_IDS,
                new_callable=AsyncMock,
                return_value=["not-a-real-integration"],
            ) as mock_connected,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        assert response.json() == {
            "targets": [
                {
                    "value": "executor",
                    "label": "General assistant",
                    "icon": "executor",
                    "connected": True,
                }
            ]
        }
        mock_connected.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(operation="list_skill_targets"),
            call(result_count=1, outcome="success"),
        ]


# ---------------------------------------------------------------------------
# GET /skills/builtin
# ---------------------------------------------------------------------------


class TestListBuiltinSkills:
    """Tests for the builtin-skills endpoint, including the _is_available /
    _group_label branch logic (executor-always-available, integration-backed
    needs a connection, non-integration builtin subagents always available)."""

    def _builtin(self, **overrides):
        from app.agents.workspace.skill_loader import BuiltinSkill

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

    async def test_executor_skill_is_always_connected(self, client: AsyncClient):
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_connected,
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        assert response.json() == {
            "skills": [
                {
                    "slug": "test-skill",
                    "name": "Test Skill",
                    "description": "does a thing",
                    "target": "executor",
                    "group_label": "General assistant",
                    "icon": "executor",
                    "connected": True,
                    "body": "# Test Skill\nDo the thing.",
                }
            ],
            "total": 1,
        }
        mock_connected.assert_awaited_once_with(USER_ID)
        assert mock_log.set.call_args_list == [
            call(operation="list_builtin_skills"),
            call(result_count=1, outcome="success"),
        ]

    async def test_non_integration_subagent_is_always_connected(self, client: AsyncClient):
        """docgen is a builtin subagent with no OAuth integration: its skills
        must stay available regardless of connected integrations."""
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(subagent_id="docgen"),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        skills = response.json()["skills"]
        assert len(skills) == 1
        assert skills[0]["connected"] is True
        assert skills[0]["group_label"] == "Document Generator"
        assert skills[0]["icon"] == "docgen"
        assert mock_log.set.call_args_list == [
            call(operation="list_builtin_skills"),
            call(result_count=1, outcome="success"),
        ]

    async def test_unknown_subagent_falls_back_to_its_id(self, client: AsyncClient):
        """A subagent id that is neither the executor nor registered anywhere
        stays available (no integration to disconnect) and labels itself."""
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(subagent_id="whoami"),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        skills = response.json()["skills"]
        assert len(skills) == 1
        assert skills[0]["connected"] is True
        assert skills[0]["group_label"] == "whoami"
        assert mock_log.set.call_args_list == [
            call(operation="list_builtin_skills"),
            call(result_count=1, outcome="success"),
        ]

    async def test_integration_backed_skill_reflects_connection_state(self, client: AsyncClient):
        """A skill mapped to a real integration subagent (gmail) must show
        connected=True only when that integration is in the connected-ids set —
        the whole reason this endpoint exists is to let the UI grey out skills
        for integrations the user hasn't connected."""
        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(subagent_id="gmail"),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        skills = response.json()["skills"]
        assert len(skills) == 1
        assert skills[0]["connected"] is False
        assert skills[0]["group_label"] == "Gmail"
        assert skills[0]["icon"] == "gmail"

        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(subagent_id="gmail"),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=["gmail"],
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        skills = response.json()["skills"]
        assert len(skills) == 1
        assert skills[0]["connected"] is True
        assert skills[0]["group_label"] == "Gmail"
        assert skills[0]["icon"] == "gmail"
        assert mock_log.set.call_args_list == [
            call(operation="list_builtin_skills"),
            call(result_count=1, outcome="success"),
        ]


# ---------------------------------------------------------------------------
# PUT /skills/{skill_id}
# ---------------------------------------------------------------------------


class TestUpdateSkill:
    """Tests for the update-skill endpoint, including _validate_target's real
    400-rejection — every test exercises it through a real request, mocking
    only get_skill_targets (its I/O seam)."""

    async def test_update_returns_200(self, client: AsyncClient):
        mock_skill = _make_skill_mock(description="updated")
        with (
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_update,
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"description": "updated"},
            )

        assert response.status_code == 200
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            skill_id="sk_abc123",
            description="updated",
            instructions=None,
            target=None,
        )
        assert mock_log.set.call_args_list == [
            call(operation="update_skill", skill_id="sk_abc123", skill={"target": None}),
            call(skill_name="my-skill", outcome="success"),
        ]

    async def test_update_with_instructions_passes_them_through(self, client: AsyncClient):
        mock_skill = _make_skill_mock(body_content="# New\nDo the new thing.")
        with (
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ) as mock_update,
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"instructions": "# New\nDo the new thing."},
            )

        assert response.status_code == 200
        assert response.json() == mock_skill.model_dump(mode="json")
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            skill_id="sk_abc123",
            description=None,
            instructions="# New\nDo the new thing.",
            target=None,
        )
        assert mock_log.set.call_args_list == [
            call(operation="update_skill", skill_id="sk_abc123", skill={"target": None}),
            call(skill_name="my-skill", outcome="success"),
        ]

    async def test_update_not_found_returns_404(self, client: AsyncClient):
        with (
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_update,
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_missing",
                json={"description": "updated"},
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Skill sk_missing not found"
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            skill_id="sk_missing",
            description="updated",
            instructions=None,
            target=None,
        )
        assert mock_log.set.call_args_list == [
            call(operation="update_skill", skill_id="sk_missing", skill={"target": None})
        ]

    async def test_update_with_disallowed_target_returns_400(self, client: AsyncClient):
        """The 400-rejection must fire through a real request: only
        get_skill_targets (the I/O boundary _validate_target depends on) is
        mocked, never _validate_target itself."""
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_targets,
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
            ) as mock_update,
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"target": "an-unconnected-integration"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Target 'an-unconnected-integration' is not available. "
            "Connect the integration before scoping a skill to it."
        )
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_update.assert_not_awaited()
        assert mock_log.set.call_args_list == [
            call(
                operation="update_skill",
                skill_id="sk_abc123",
                skill={"target": "an-unconnected-integration"},
            )
        ]
        mock_log.error.assert_not_called()

    async def test_update_with_allowed_target_succeeds(self, client: AsyncClient):
        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[EXECUTOR_TARGET],
            ) as mock_targets,
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                return_value=_make_skill_mock(target="executor"),
            ) as mock_update,
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"target": "executor"},
            )

        assert response.status_code == 200
        assert response.json()["target"] == "executor"
        mock_targets.assert_awaited_once_with(USER_ID)
        mock_update.assert_awaited_once_with(
            user_id=USER_ID,
            skill_id="sk_abc123",
            description=None,
            instructions=None,
            target="executor",
        )
        assert mock_log.set.call_args_list == [
            call(operation="update_skill", skill_id="sk_abc123", skill={"target": "executor"}),
            call(skill_name="my-skill", outcome="success"),
        ]

    async def test_update_value_error_returns_400(self, client: AsyncClient):
        with (
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                side_effect=ValueError("Bad skill update"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"description": "updated"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Bad skill update"
        mock_log.error.assert_not_called()

    async def test_update_service_error_returns_500(self, client: AsyncClient):
        with (
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB error"),
            ),
            patch(_LOG) as mock_log,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"description": "updated"},
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to update skill"
        mock_log.error.assert_called_once_with(
            f"{LogTag.SKILLS} Error updating skill",
            user_id=USER_ID,
            skill_id="sk_abc123",
            error_type="RuntimeError",
            error="DB error",
        )
