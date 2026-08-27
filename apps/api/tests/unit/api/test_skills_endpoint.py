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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.services.analytics_service import AnalyticsEvents

if TYPE_CHECKING:
    from app.agents.skills.github_discovery import DiscoveredSkill
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
_GET_SKILL_TARGETS = "app.api.v1.endpoints.skills.get_skill_targets"
_GET_CONNECTED_INTEGRATION_IDS = "app.agents.skills.targets.get_connected_integration_ids"
_LOAD_BUILTIN_SKILLS = "app.api.v1.endpoints.skills.load_builtin_skills"
_GET_CONNECTED_INTEGRATION_IDS_ENDPOINT = (
    "app.api.v1.endpoints.skills.get_connected_integration_ids"
)
_UPDATE_SKILL_INLINE = "app.api.v1.endpoints.skills.update_skill_inline"
_CAPTURE = "app.api.v1.endpoints.skills.capture_context_event"


def _make_skill_mock(**overrides) -> Skill:
    from app.agents.skills.models import Skill

    base: dict[str, Any] = {
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
    return Skill(**base)


def _make_discovered_skill(**overrides) -> DiscoveredSkill:
    from app.agents.skills.github_discovery import DiscoveredSkill

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
# GET /skills/discover
# ---------------------------------------------------------------------------


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
        assert data["branch"] == "main"
        assert data["count"] == 1
        assert data["skills"] == [
            {
                "name": "my-skill",
                "description": "Discovered skill",
                "path": "skills/my-skill",
                "repo_url": "https://github.com/owner/repo",
                "subagent_id": "executor",
            }
        ]

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


class TestInstallFromGitHub:
    """Tests for the install skill from GitHub endpoint."""

    async def test_install_with_skill_path_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock(target="gmail_agent")
        with (
            patch(
                "app.api.v1.endpoints.skills.get_skill_targets",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ),
            patch(_CAPTURE) as mock_capture,
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={
                    "repo_url": "owner/repo",
                    "skill_path": "skills/my-skill",
                },
            )

        assert response.status_code == 201
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SKILL_INSTALLED,
            {"skill_id": "sk_abc123", "target": "gmail_agent", "source": "github"},
        )

    async def test_install_with_skill_name_auto_discovers(self, client: AsyncClient):
        mock_discovered = _make_discovered_skill(path="skills/my-skill")
        mock_skill = _make_skill_mock()
        with (
            patch(
                "app.api.v1.endpoints.skills.get_skill_targets",
                new_callable=AsyncMock,
                return_value=[],
            ),
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
        with (
            patch(
                "app.api.v1.endpoints.skills.get_skill_targets",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _GET_SKILL_FROM_REPO,
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo", "skill_name": "nonexistent"},
            )

        assert response.status_code == 404

    async def test_install_no_path_or_name_returns_400(self, client: AsyncClient):
        with patch(
            "app.api.v1.endpoints.skills.get_skill_targets",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.post(
                INSTALL_GITHUB_URL,
                params={"repo_url": "owner/repo"},
            )
        assert response.status_code == 400

    async def test_install_missing_repo_url_returns_422(self, client: AsyncClient):
        response = await client.post(INSTALL_GITHUB_URL)
        assert response.status_code == 422

    async def test_install_value_error_returns_400(self, client: AsyncClient):
        with (
            patch(
                "app.api.v1.endpoints.skills.get_skill_targets",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid skill format"),
            ),
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
        with (
            patch(
                "app.api.v1.endpoints.skills.get_skill_targets",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                _INSTALL_GITHUB,
                new_callable=AsyncMock,
                side_effect=RuntimeError("GitHub API rate limited"),
            ),
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


class TestInstallInline:
    """Tests for the create inline skill endpoint."""

    async def test_create_inline_skill_returns_201(self, client: AsyncClient):
        mock_skill = _make_skill_mock(source="inline", target="gmail_agent")
        with (
            patch(
                "app.api.v1.endpoints.skills._validate_target",
                new_callable=AsyncMock,
            ),
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
                return_value=mock_skill,
            ),
            patch(_CAPTURE) as mock_capture,
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
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SKILL_INSTALLED,
            {"skill_id": "sk_abc123", "target": "gmail_agent", "source": "inline"},
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
        # _validate_target calls get_skill_targets which makes DB calls; bypass it
        # so the test exercises the ValueError→400 mapping in the endpoint handler.
        with (
            patch(
                "app.api.v1.endpoints.skills._validate_target",
                new_callable=AsyncMock,
            ),
            patch(
                _INSTALL_INLINE,
                new_callable=AsyncMock,
                side_effect=ValueError("Duplicate skill name"),
            ),
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


class TestUninstallSkill:
    """Tests for the uninstall skill endpoint."""

    async def test_uninstall_skill_returns_204(self, client: AsyncClient):
        with (
            patch(
                _UNINSTALL_SKILL,
                new_callable=AsyncMock,
                return_value=_make_skill_mock(target="gmail_agent"),
            ) as mock_uninstall,
            patch(_CAPTURE) as mock_capture,
        ):
            response = await client.delete(f"{BASE_URL}/sk_abc123")

        assert response.status_code == 204
        # Whose skill and which skill is the whole payload of a destructive
        # call: a dropped or None argument deletes nothing, or another user's
        # skill, while the endpoint still answers 204.
        mock_uninstall.assert_awaited_once_with("507f1f77bcf86cd799439011", "sk_abc123")
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SKILL_UNINSTALLED,
            {"skill_id": "sk_abc123", "target": "gmail_agent"},
        )

    async def test_uninstall_skill_not_found_returns_404(self, client: AsyncClient):
        with patch(
            _UNINSTALL_SKILL,
            new_callable=AsyncMock,
            return_value=None,
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


# ---------------------------------------------------------------------------
# GET /skills/targets
# ---------------------------------------------------------------------------


class TestListSkillTargets:
    """Tests for the skill-targets endpoint. Mocks only get_connected_integration_ids
    (the true I/O boundary) so get_skill_targets' own executor+connected-subagent
    assembly logic runs for real."""

    async def test_returns_executor_plus_connected_integration(self, client: AsyncClient):
        with patch(
            _GET_CONNECTED_INTEGRATION_IDS,
            new_callable=AsyncMock,
            return_value=["gmail"],
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        values = [t["value"] for t in response.json()["targets"]]
        assert "executor" in values
        # Target value is the subagent's agent_name, not the raw integration id.
        assert "gmail_agent" in values

    async def test_no_connected_integrations_returns_executor_only(self, client: AsyncClient):
        with patch(
            _GET_CONNECTED_INTEGRATION_IDS,
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        targets = response.json()["targets"]
        assert [t["value"] for t in targets] == ["executor"]

    async def test_unknown_connected_integration_id_is_skipped(self, client: AsyncClient):
        """An id with no subagent registration (or no subagent config) must be
        skipped, not surfaced as a broken/blank target the UI can select."""
        with patch(
            _GET_CONNECTED_INTEGRATION_IDS,
            new_callable=AsyncMock,
            return_value=["not-a-real-integration"],
        ):
            response = await client.get(f"{BASE_URL}/targets")

        assert response.status_code == 200
        targets = response.json()["targets"]
        assert [t["value"] for t in targets] == ["executor"]


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
            ),
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        skills = response.json()["skills"]
        assert len(skills) == 1
        assert skills[0]["connected"] is True
        assert skills[0]["group_label"] == "General assistant"

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
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        assert response.json()["skills"][0]["connected"] is False

        with (
            patch(_LOAD_BUILTIN_SKILLS, return_value=(self._builtin(subagent_id="gmail"),)),
            patch(
                _GET_CONNECTED_INTEGRATION_IDS_ENDPOINT,
                new_callable=AsyncMock,
                return_value=["gmail"],
            ),
        ):
            response = await client.get(f"{BASE_URL}/builtin")

        assert response.status_code == 200
        assert response.json()["skills"][0]["connected"] is True


# ---------------------------------------------------------------------------
# PUT /skills/{skill_id}
# ---------------------------------------------------------------------------


class TestUpdateSkill:
    """Tests for the update-skill endpoint, including _validate_target's real
    400-rejection — every prior test that touched this path mocked
    _validate_target itself into a no-op, so its rejection was never actually
    proven through a real request."""

    async def test_update_returns_200(self, client: AsyncClient):
        with patch(
            _UPDATE_SKILL_INLINE,
            new_callable=AsyncMock,
            return_value=_make_skill_mock(description="updated"),
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"description": "updated"},
            )

        assert response.status_code == 200
        assert response.json()["description"] == "updated"

    async def test_update_not_found_returns_404(self, client: AsyncClient):
        with patch(
            _UPDATE_SKILL_INLINE,
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = await client.put(
                f"{BASE_URL}/sk_missing",
                json={"description": "updated"},
            )

        assert response.status_code == 404

    async def test_update_with_disallowed_target_returns_400(self, client: AsyncClient):
        """Mocks only get_skill_targets (the I/O boundary _validate_target
        depends on), not _validate_target itself — this is what proves the
        400-rejection actually fires through a real request."""
        with patch(
            _GET_SKILL_TARGETS,
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"target": "an-unconnected-integration"},
            )

        assert response.status_code == 400
        assert "not available" in response.json()["detail"]

    async def test_update_with_allowed_target_succeeds(self, client: AsyncClient):
        from app.agents.skills.models import SkillTarget

        with (
            patch(
                _GET_SKILL_TARGETS,
                new_callable=AsyncMock,
                return_value=[
                    SkillTarget(value="executor", label="General assistant", icon="executor")
                ],
            ),
            patch(
                _UPDATE_SKILL_INLINE,
                new_callable=AsyncMock,
                return_value=_make_skill_mock(target="executor"),
            ),
        ):
            response = await client.put(
                f"{BASE_URL}/sk_abc123",
                json={"target": "executor"},
            )

        assert response.status_code == 200
        assert response.json()["target"] == "executor"
