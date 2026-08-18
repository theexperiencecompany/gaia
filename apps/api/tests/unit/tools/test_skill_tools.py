"""Unit tests for app.agents.tools.skill_tools."""

from collections.abc import Awaitable, Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.skill_tools import (
    LearnedSkillSpec,
    _compose_learned_skill_md,
    save_learned_skill,
)
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.skill_tools"


#: What a step's blank-value rejection must say. Asserted verbatim: the field
#: name alone is in the error whatever the validator raises, so a looser match
#: passes even when the message stops telling the model what went wrong.
_BLANK_STEP_MSG = "Value error, must not be blank"


def _blank_step_errors(exc: ValidationError) -> list[tuple[tuple[Any, ...], str]]:
    """``exc``'s value_error entries as (location, message) pairs, in order."""
    return [(e["loc"], e["msg"]) for e in exc.errors() if e["type"] == "value_error"]


def _cfg(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    return {"metadata": {"user_id": user_id}}


def _cfg_no_user() -> dict[str, Any]:
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
        mock_install.return_value = _installed_skill(files=["SKILL.md", "script.py", "data.json"])

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

    @patch(f"{MODULE}.list_skills", new_callable=AsyncMock, side_effect=RuntimeError("err"))
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

    @patch(f"{MODULE}.uninstall_skill_full", new_callable=AsyncMock)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_uninstall(self, mock_get: AsyncMock, mock_uninstall: AsyncMock) -> None:
        mock_get.return_value = _skill_record()
        mock_uninstall.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="uninstall"
        )
        assert "uninstalled" in result
        # Which user and which skill is the whole payload of a destructive
        # call: a dropped or None argument deletes nothing, or the wrong
        # thing, while the tool still reports success.
        mock_uninstall.assert_awaited_once_with(FAKE_USER_ID, "skill-1")

    @patch(f"{MODULE}.uninstall_skill_full", new_callable=AsyncMock, return_value=None)
    @patch(f"{MODULE}.get_skill_by_name", new_callable=AsyncMock)
    async def test_uninstall_failed(self, mock_get: AsyncMock, mock_uninstall: AsyncMock) -> None:
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
    async def test_already_enabled(self, mock_get: AsyncMock, mock_enable: AsyncMock) -> None:
        mock_get.return_value = _skill_record()

        from app.agents.tools.skill_tools import manage_skill

        result = await manage_skill.coroutine(  # type: ignore[attr-defined]
            config=_cfg(), skill_name="pdf-processing", action="enable"
        )
        assert "already enabled" in result


# ---------------------------------------------------------------------------
# Tests: save_learned_skill
# ---------------------------------------------------------------------------


def _invoke_save_learned_skill(config: dict[str, Any], spec: dict[str, Any]) -> Any:
    """Call the decorated tool's coroutine with its config, typed at the seam."""
    coroutine = cast("Callable[..., Awaitable[Any]]", save_learned_skill.coroutine)
    return coroutine(config=config, spec=LearnedSkillSpec(**spec))


def _learned_spec(**overrides: Any) -> dict[str, Any]:
    spec = {
        "name": "triage-inbox",
        "description": "Triage the inbox: archive promos/newsletters, flag action-needed mail",
        "target": "executor",
        "when_to_use": "User asks to clean up, triage, or organize their inbox.",
        "integrations": ["gmail"],
        "steps": [
            {
                "goal": "Find the unread mail",
                "tool": "gmail_search",
                "args": {"query": "is:unread"},
                "notes": "List ids, not full bodies.",
            },
            {
                "goal": "Archive promos",
                "tool": "gmail_archive",
                "args": {"email_id": "<id from step 1>"},
            },
        ],
    }
    spec.update(overrides)
    return spec


@pytest.mark.unit
class TestLearnedSkillSpecValidation:
    def test_empty_steps_rejected(self) -> None:
        with pytest.raises(ValueError, match="steps"):
            LearnedSkillSpec(**_learned_spec(steps=[]))

    def test_blank_goal_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LearnedSkillSpec(**_learned_spec(steps=[{"goal": "  ", "tool": "gmail_search"}]))

        assert _blank_step_errors(exc.value) == [(("steps", 0, "goal"), _BLANK_STEP_MSG)]

    def test_blank_tool_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LearnedSkillSpec(**_learned_spec(steps=[{"goal": "Do it", "tool": "   "}]))

        assert _blank_step_errors(exc.value) == [(("steps", 0, "tool"), _BLANK_STEP_MSG)]

    def test_blank_goal_and_tool_are_each_reported(self) -> None:
        with pytest.raises(ValidationError) as exc:
            LearnedSkillSpec(**_learned_spec(steps=[{"goal": "", "tool": "\t"}]))

        assert _blank_step_errors(exc.value) == [
            (("steps", 0, "goal"), _BLANK_STEP_MSG),
            (("steps", 0, "tool"), _BLANK_STEP_MSG),
        ]

    def test_whitespace_padded_values_are_accepted_verbatim(self) -> None:
        # The validator rejects blanks; it must not silently strip a real value.
        spec = LearnedSkillSpec(
            **_learned_spec(steps=[{"goal": " Do it ", "tool": " gmail_search "}])
        )

        assert spec.steps[0].goal == " Do it "
        assert spec.steps[0].tool == " gmail_search "


@pytest.mark.unit
class TestComposeLearnedSkillMd:
    def test_composes_comprehensive_body(self) -> None:
        body = _compose_learned_skill_md(LearnedSkillSpec(**_learned_spec()))
        assert "## When to Activate" in body
        assert "triage, or organize their inbox" in body
        assert "## Prerequisites" in body
        assert "`gmail`" in body
        assert "## Steps" in body
        assert "### Step 1: Find the unread mail" in body
        assert "Call `gmail_search` with:" in body
        assert '"query": "is:unread"' in body
        assert "### Step 2: Archive promos" in body
        assert '"email_id": "<id from step 1>"' in body
        assert "List ids, not full bodies." in body

    def test_omits_optional_sections(self) -> None:
        spec = _learned_spec(when_to_use="", integrations=[])
        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))
        assert "## When to Activate" not in body
        assert "## Prerequisites" not in body
        assert "## Steps" in body

    def test_step_without_args_says_none(self) -> None:
        spec = _learned_spec()
        spec["steps"] = [{"goal": "Do the thing", "tool": "finish_task"}]
        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))
        assert "Call `finish_task` with:" in body
        assert "- no arguments" in body


@pytest.mark.unit
class TestSaveLearnedSkill:
    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_happy_path(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill(name="triage-inbox")

        result = await _invoke_save_learned_skill(_cfg(), _learned_spec())
        assert "Saved skill 'triage-inbox'" in result
        assert "Steps: 2" in result
        assert "gmail" in result
        assert "executor" in result

        call_kwargs = mock_install.call_args[1]
        assert call_kwargs["user_id"] == FAKE_USER_ID
        assert call_kwargs["name"] == "triage-inbox"
        assert call_kwargs["target"] == "executor"
        assert call_kwargs["extra_metadata"] == {"source": "learned", "learned_from_run": "1"}
        assert "## Steps" in call_kwargs["instructions"]

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=ValueError("Bad name"),
    )
    async def test_validation_error_is_safe(self, mock_install: AsyncMock) -> None:
        result = await _invoke_save_learned_skill(_cfg(), _learned_spec())
        assert result == (
            "Failed to save skill: the recipe is invalid (check the name and step fields)."
        )
        # The underlying reason must stay out of the executor-facing message.
        assert "Bad name" not in result

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Disk"),
    )
    async def test_general_error_is_safe(self, mock_install: AsyncMock) -> None:
        result = await _invoke_save_learned_skill(_cfg(), _learned_spec())
        assert result == "Error saving skill: the skill could not be persisted. Try again."
        # No filesystem/implementation detail may leak to the executor.
        assert "Disk" not in result

    async def test_no_user_id(self) -> None:
        with pytest.raises(ValueError, match="User ID not found"):
            await _invoke_save_learned_skill(_cfg_no_user(), _learned_spec())

    async def test_subagent_target(self) -> None:
        spec = _learned_spec(target="github_agent", name="pr-summary", integrations=["github"])
        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))
        assert "## Prerequisites" in body
        assert "`github`" in body


# ---------------------------------------------------------------------------
# Learned skills: the exact artifact, and what the run records
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLearnedSkillArtifactIsExact:
    """SKILL.md is read back by an agent as its instructions, so its layout is the
    contract — headings, fenced JSON, and the blank lines between steps all carry
    meaning. The sibling tests assert with ``in``, which cannot see a heading
    being renamed (mutmut's ``"XX## StepsXX"`` still *contains* ``"## Steps"``)
    or the sections being reordered."""

    def test_the_composed_body_is_exact(self) -> None:
        body = _compose_learned_skill_md(LearnedSkillSpec(**_learned_spec()))

        assert body == (
            "## When to Activate\n"
            "User asks to clean up, triage, or organize their inbox.\n"
            "\n"
            "## Prerequisites\n"
            "These integrations must be connected for this skill to work:\n"
            "- `gmail`\n"
            "\n"
            "## Steps\n"
            "### Step 1: Find the unread mail\n"
            "Call `gmail_search` with:\n"
            "```json\n"
            "{\n"
            '  "query": "is:unread"\n'
            "}\n"
            "```\n"
            "\n"
            "List ids, not full bodies.\n"
            "\n"
            "### Step 2: Archive promos\n"
            "Call `gmail_archive` with:\n"
            "```json\n"
            "{\n"
            '  "email_id": "<id from step 1>"\n'
            "}\n"
            "```\n"
        )

    def test_the_minimal_body_is_exact(self) -> None:
        """No trigger section, no prerequisites, and a step that takes no arguments
        — the shape a one-tool skill saves as."""
        spec = _learned_spec(
            when_to_use="",
            integrations=[],
            steps=[{"goal": "Do the thing", "tool": "finish_task"}],
        )

        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))

        assert body == (
            "## Steps\n### Step 1: Do the thing\nCall `finish_task` with:\n- no arguments\n"
        )

    def test_step_notes_are_stripped_and_kept_out_of_the_json_fence(self) -> None:
        spec = _learned_spec(
            steps=[
                {
                    "goal": "  Check the result  ",
                    "tool": "read",
                    "args": {},
                    "notes": "  Verify before moving on.  ",
                }
            ]
        )

        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))

        assert body == (
            "## When to Activate\n"
            "User asks to clean up, triage, or organize their inbox.\n"
            "\n"
            "## Prerequisites\n"
            "These integrations must be connected for this skill to work:\n"
            "- `gmail`\n"
            "\n"
            "## Steps\n"
            "### Step 1: Check the result\n"
            "Call `read` with:\n"
            "- no arguments\n"
            "\n"
            "Verify before moving on.\n"
        )

    def test_non_ascii_step_args_stay_readable(self) -> None:
        """The args block is instructions an agent reads back and re-sends. Escaping
        non-ASCII to \\uXXXX turns a searchable subject line into something the
        model has to decode before it can reuse it."""
        spec = _learned_spec(
            steps=[
                {
                    "goal": "Find the receipt",
                    "tool": "gmail_search",
                    "args": {"query": "subject:café ☕"},
                }
            ]
        )

        body = _compose_learned_skill_md(LearnedSkillSpec(**spec))

        assert '"query": "subject:café ☕"' in body
        assert "\\u" not in body


@pytest.mark.unit
class TestSaveLearnedSkillRecordsTheRun:
    """What the executor is told, and what the wide event carries afterwards. The
    tool's return value is the agent's only view of the outcome, and ``log.set``
    is how a failed save is findable in production."""

    @pytest.fixture(autouse=True)
    def _fresh_wide_event(self) -> None:
        log.reset()

    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_the_summary_handed_back_to_the_agent_is_exact(
        self, mock_install: AsyncMock
    ) -> None:
        mock_install.return_value = _installed_skill(
            name="triage-inbox", target="executor", vfs_path="/skills/triage-inbox"
        )

        result = await _invoke_save_learned_skill(_cfg(), _learned_spec())

        assert result == (
            "Saved skill 'triage-inbox' successfully.\n"
            "- Target: executor\n"
            "- Integrations: gmail\n"
            "- Steps: 2\n"
            "- Location: /skills/triage-inbox/SKILL.md\n"
            "- The skill is now active and will appear in the executor agent's "
            "Available Skills. Next time this task comes up, it runs the saved steps "
            "instead of re-deriving them."
        )

    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_a_skill_with_no_integrations_reports_none(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill(name="tidy", vfs_path="/skills/tidy")

        result = await _invoke_save_learned_skill(_cfg(), _learned_spec(integrations=[]))

        assert "- Integrations: none\n" in result

    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_multiple_integrations_are_listed_comma_separated(
        self, mock_install: AsyncMock
    ) -> None:
        mock_install.return_value = _installed_skill(name="cross-post")

        result = await _invoke_save_learned_skill(
            _cfg(), _learned_spec(integrations=["gmail", "github", "slack"])
        )

        assert "- Integrations: gmail, github, slack\n" in result

    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_the_spec_description_is_what_gets_installed(
        self, mock_install: AsyncMock
    ) -> None:
        """The description is what the agent matches against when deciding whether
        to activate the skill, so installing the wrong one makes it undiscoverable."""
        mock_install.return_value = _installed_skill(name="triage-inbox")

        await _invoke_save_learned_skill(_cfg(), _learned_spec())

        assert mock_install.call_args[1]["description"] == (
            "Triage the inbox: archive promos/newsletters, flag action-needed mail"
        )

    @patch(f"{MODULE}.install_from_inline", new_callable=AsyncMock)
    async def test_a_successful_save_is_on_the_wide_event(self, mock_install: AsyncMock) -> None:
        mock_install.return_value = _installed_skill(name="triage-inbox")

        await _invoke_save_learned_skill(_cfg(), _learned_spec())

        assert log.get()["tool"] == {"name": "save_learned_skill", "action": "save"}

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=ValueError("Bad name"),
    )
    async def test_an_invalid_spec_is_findable_on_the_wide_event(
        self, mock_install: AsyncMock
    ) -> None:
        """``error`` is what separates a rejected recipe from a storage failure when
        someone asks why a user's skill never saved."""
        await _invoke_save_learned_skill(_cfg(), _learned_spec())

        assert log.get()["tool"] == {
            "name": "save_learned_skill",
            "action": "save",
            "error": "invalid_spec",
        }
        errors = log.get()["errors"]
        assert len(errors) == 1
        assert isinstance(errors[0]["msg"], str) and errors[0]["msg"]
        assert errors[0]["error"] == "Bad name"
        assert errors[0]["user_id"] == FAKE_USER_ID

    @patch(
        f"{MODULE}.install_from_inline",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Disk"),
    )
    async def test_a_persistence_failure_is_findable_on_the_wide_event(
        self, mock_install: AsyncMock
    ) -> None:
        await _invoke_save_learned_skill(_cfg(), _learned_spec())

        assert log.get()["tool"] == {
            "name": "save_learned_skill",
            "action": "save",
            "error": "persist_failed",
        }
        errors = log.get()["errors"]
        assert len(errors) == 1
        assert isinstance(errors[0]["msg"], str) and errors[0]["msg"]
        assert errors[0]["error"] == "Disk"
        assert errors[0]["user_id"] == FAKE_USER_ID
