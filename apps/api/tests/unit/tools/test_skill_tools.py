"""Unit tests for app.agents.tools.skill_tools."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.skill_tools"


def _cfg(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    return {"metadata": {"user_id": user_id}}


def _cfg_no_user() -> Dict[str, Any]:
    return {"metadata": {}}


def _installed_skill(**overrides: Any) -> MagicMock:
    defaults = {
        "name": "pdf-processing",
        "description": "Process PDFs",
        "target": "executor",
        "vfs_path": "/skills/pdf-processing",
        "source_url": "https://github.com/owner/repo",
        "files": ["SKILL.md"],
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _skill_record(**overrides: Any) -> MagicMock:
    defaults = {
        "id": "skill-1",
        "name": "pdf-processing",
        "description": "Process PDFs",
        "target": "executor",
        "vfs_path": "/skills/pdf-processing",
        "enabled": True,
        "source_url": "https://github.com/owner/repo",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    mock.source = MagicMock()
    mock.source.value = overrides.get("source_value", "github")
    return mock


# ---------------------------------------------------------------------------
# Tests: _get_user_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserId:
    def test_extracts_user_id(self) -> None:
        from app.agents.tools.skill_tools import _get_user_id

        assert _get_user_id(_cfg()) == FAKE_USER_ID  # type: ignore[arg-type]

    def test_missing_user_id_raises(self) -> None:
        from app.agents.tools.skill_tools import _get_user_id

        with pytest.raises(ValueError, match="User ID not found"):
            _get_user_id(_cfg_no_user())  # type: ignore[arg-type]

    def test_none_config(self) -> None:
        from app.agents.tools.skill_tools import _get_user_id

        with pytest.raises(ValueError, match="User ID not found"):
            _get_user_id(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: install_skill_from_github
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInstallSkillFromGithub:
    @patch(f"{MODULE}.install_from_github", new_callable=AsyncMock)
    async def test_happy_path(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill()

        from app.agents.tools.skill_tools import install_skill_from_github

        result = await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), repo_url="owner/repo", skill_path="skills/pdf"
        )
        assert "Installed skill 'pdf-processing'" in result
        assert "executor" in result

    @patch(f"{MODULE}.install_from_github", new_callable=AsyncMock)
    async def test_multiple_files(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill(
            files=["SKILL.md", "script.py", "data.json"]
        )

        from app.agents.tools.skill_tools import install_skill_from_github

        result = await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), repo_url="owner/repo"
        )
        assert "3 files" in result

    @patch(
        f"{MODULE}.install_from_github",
        new_callable=AsyncMock,
        side_effect=ValueError("Bad URL"),
    )
    async def test_validation_error(self, mock_install: AsyncMock) -> None:
        from app.agents.tools.skill_tools import install_skill_from_github

        result = await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), repo_url="bad"
        )
        assert "Failed to install skill" in result
        assert "Bad URL" in result

    @patch(
        f"{MODULE}.install_from_github",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Network"),
    )
    async def test_general_error(self, mock_install: AsyncMock) -> None:
        from app.agents.tools.skill_tools import install_skill_from_github

        result = await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), repo_url="owner/repo"
        )
        assert "Error installing skill from GitHub" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.skill_tools import install_skill_from_github

        with pytest.raises(ValueError, match="User ID not found"):
            await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
                config=_cfg_no_user(), repo_url="owner/repo"
            )

    @patch(f"{MODULE}.install_from_github", new_callable=AsyncMock)
    async def test_empty_skill_path_and_target(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill()

        from app.agents.tools.skill_tools import install_skill_from_github

        await install_skill_from_github.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), repo_url="owner/repo", skill_path="", target=""
        )
        # Should pass None for empty strings
        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["skill_path"] is None
        assert call_kwargs["target_override"] is None


# ---------------------------------------------------------------------------
# Tests: create_skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSkill:
    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_happy_path(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill(name="standup-format")

        from app.agents.tools.skill_tools import create_skill

        result = await create_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(),
            name="standup-format",
            description="Format standups",
            instructions="# Steps\n1. ...",
            target="slack_agent",
        )
        assert "Created skill 'standup-format'" in result
        assert "slack_agent" in result

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=ValueError("Bad name"),
    )
    async def test_validation_error(self, mock_install: AsyncMock) -> None:
        from app.agents.tools.skill_tools import create_skill

        result = await create_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), name="bad!", description="d", instructions="i"
        )
        assert "Failed to create skill" in result

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Disk"),
    )
    async def test_general_error(self, mock_install: AsyncMock) -> None:
        from app.agents.tools.skill_tools import create_skill

        result = await create_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), name="test", description="d", instructions="i"
        )
        assert "Error creating skill" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.skill_tools import create_skill

        with pytest.raises(ValueError, match="User ID not found"):
            await create_skill.coroutine(  # type: ignore[attr-defined]
                config=_cfg_no_user(), name="test", description="d", instructions="i"
            )


# ---------------------------------------------------------------------------
# Tests: list_installed_skills
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListInstalledSkills:
    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock)
    async def test_happy_path(self, mock_list: AsyncMock) -> None:
        mock_list.return_value = [
            _skill_record(),
            _skill_record(name="email-templates"),
        ]

        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "Installed skills (2)" in result
        assert "pdf-processing" in result
        assert "email-templates" in result

    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock, return_value=[])
    async def test_empty(self, mock_list: AsyncMock) -> None:
        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "No skills installed" in result

    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock, return_value=[])
    async def test_filter_by_target(self, mock_list: AsyncMock) -> None:
        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg(), target="executor")  # type: ignore[attr-defined]
        mock_list.assert_awaited_once_with(user_id=FAKE_USER_ID, target="executor")
        assert "for target 'executor'" in result

    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock)
    async def test_with_source_url(self, mock_list: AsyncMock) -> None:
        skill = _skill_record(source_url="https://github.com/owner/repo")
        mock_list.return_value = [skill]

        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "Source URL" in result

    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock)
    async def test_disabled_skill(self, mock_list: AsyncMock) -> None:
        skill = _skill_record(enabled=False, source_url=None)
        mock_list.return_value = [skill]

        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "disabled" in result

    @patch(
        f"{MODULE}.list_skills", new_callable=AsyncMock, side_effect=RuntimeError("err")
    )
    async def test_error(self, mock_list: AsyncMock) -> None:
        from app.agents.tools.skill_tools import list_installed_skills

        result = await list_installed_skills.coroutine(config=_cfg())  # type: ignore[attr-defined]
        assert "Error listing skills" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.skill_tools import list_installed_skills

        with pytest.raises(ValueError, match="User ID not found"):
            await list_installed_skills.coroutine(config=_cfg_no_user())  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: manage_skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestManageSkill:
    @patch(f"{MODULE}.enable_skill", new_callable=AsyncMock, return_value=True)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_enable(self, mock_get: AsyncMock, mock_enable: AsyncMock) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="enable"
        )
        assert "enabled" in result
        mock_enable.assert_awaited_once()

    @patch(f"{MODULE}.disable_skill", new_callable=AsyncMock, return_value=True)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_disable(self, mock_get: AsyncMock, mock_disable: AsyncMock) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="disable"
        )
        assert "disabled" in result

    @patch(f"{MODULE}.uninstall_skill_full", new_callable=AsyncMock, return_value=True)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_uninstall(
        self, mock_get: AsyncMock, mock_uninstall: AsyncMock
    ) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="uninstall"
        )
        assert "uninstalled" in result

    @patch(f"{MODULE}.uninstall_skill_full", new_callable=AsyncMock, return_value=False)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_uninstall_failed(
        self, mock_get: AsyncMock, mock_uninstall: AsyncMock
    ) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="uninstall"
        )
        assert "Failed to uninstall" in result

    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock, return_value=None)
    async def test_skill_not_found(self, mock_get: AsyncMock) -> None:
        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="nonexistent", action="enable"
        )
        assert "not found" in result

    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_unknown_action(self, mock_get: AsyncMock) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="restart"
        )
        assert "Unknown action" in result

    @patch(
        f"{MODULE}.get_skill_by_name",
        new_callable=AsyncMock,
        side_effect=RuntimeError("err"),
    )
    async def test_error(self, mock_get: AsyncMock) -> None:
        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="enable"
        )
        assert "Error managing skill" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.skill_tools import manage_skill

        with pytest.raises(ValueError, match="User ID not found"):
            await manage_skill.coroutine(  # type: ignore[attr-defined]
                config=_cfg_no_user(), skill_name="test", action="enable"
            )

    @patch(f"{MODULE}.enable_skill", new_callable=AsyncMock, return_value=False)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_already_enabled(
        self, mock_get: AsyncMock, mock_enable: AsyncMock
    ) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="enable"
        )
        assert "already enabled" in result
