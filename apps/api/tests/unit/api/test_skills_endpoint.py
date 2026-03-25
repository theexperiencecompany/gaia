"""Unit tests for the skills API endpoints.

Tests cover:
- GET    /api/v1/skills/discover
- POST   /api/v1/skills/install/github
- POST   /api/v1/skills/install/inline
- GET    /api/v1/skills
- GET    /api/v1/skills/{skill_id}
- PATCH  /api/v1/skills/{skill_id}/enable
- PATCH  /api/v1/skills/{skill_id}/disable
- DELETE /api/v1/skills/{skill_id}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

if TYPE_CHECKING:
    from app.agents.skills.models import Skill

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


def _make_skill_mock(**overrides) -> "Skill":
    from app.agents.skills.models import Skill

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
        "installed_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
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
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 201

    async def test_install_with_skill_name_auto_discovers(self, client: AsyncClient):
        mock_discovered = _make_discovered_skill(path="skills/my-skill")
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
            ),
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "my-skill"},
            )

        assert response.status_code == 201

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

    async def test_create_inline_skill_missing_name_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "description": "Does something",
                "instructions": "Do the thing.",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_missing_description_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "name": "my-skill",
                "instructions": "Do the thing.",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_missing_instructions_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            INSTALL_INLINE_URL,
            json={
                "name": "my-skill",
                "description": "Does something useful",
            },
        )
        assert response.status_code == 422

    async def test_create_inline_skill_value_error_returns_400(
        self, client: AsyncClient
    ):
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

    async def test_create_inline_skill_service_error_returns_500(
        self, client: AsyncClient
    ):
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
        mock_skills = [_make_skill_mock()]
        with patch(
            _LIST_SKILLS,
            new_callable=AsyncMock,
            return_value=mock_skills,
        ):
            response = await client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

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
        ):
            response = await client.get(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 200

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
