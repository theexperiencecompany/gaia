"""workflow_utils: config extraction, the trigger diff, and the edit apply path.

The config helpers must fail loud when the key is absent; the edit helpers must
change exactly the trigger fields the draft actually changed, and no others.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.constants.log_tags import LogTag
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.workflow.subagent_output import FinalizedOutput
from app.utils.workflow_utils import (
    WorkflowConfigError,
    _edited_trigger,
    _regenerated_after_prompt_edit,
    apply_workflow_edit,
    create_workflow_directly,
    get_user_id,
    get_workflow_id,
)

USER_ID = "507f1f77bcf86cd799439011"
SERVICE = "app.services.workflow.service.WorkflowService"


def _draft(**overrides: object) -> FinalizedOutput:
    fields: dict[str, object] = {
        "type": "finalized",
        "title": "Morning digest",
        "description": "A daily digest",
        "prompt": "Summarize my inbox",
        "trigger_type": "scheduled",
    }
    fields.update(overrides)
    return FinalizedOutput(**fields)  # type: ignore[arg-type]  # overrides bag is dict[str, object] by design; pydantic validates


def _workflow(trigger_config: TriggerConfig, **overrides: object) -> Workflow:
    fields: dict[str, object] = {
        "user_id": USER_ID,
        "title": "Morning digest",
        "description": "A daily digest",
        "prompt": "Summarize my inbox",
        "steps": [],
        "trigger_config": trigger_config,
    }
    fields.update(overrides)
    return Workflow(**fields)  # type: ignore[arg-type]  # overrides bag is dict[str, object] by design; pydantic validates


@pytest.mark.unit
class TestGetWorkflowId:
    def test_returns_the_configurable_workflow_id(self) -> None:
        config: RunnableConfig = {"configurable": {"workflow_id": "wf_9f674ef3558f"}}
        assert get_workflow_id(config) == "wf_9f674ef3558f"

    def test_a_config_without_a_workflow_id_says_workflow_runs_only(self) -> None:
        # The playbook tools are bound to the executor in chat runs too, so the
        # error is what the model reads when it calls one outside a workflow.
        config: RunnableConfig = {"configurable": {"user_id": "u1"}}
        with pytest.raises(WorkflowConfigError) as exc:
            get_workflow_id(config)
        assert str(exc.value) == (
            "No workflow in this run's config: this tool only works inside a workflow run."
        )

    def test_a_config_with_no_configurable_raises_the_same_error(self) -> None:
        with pytest.raises(WorkflowConfigError, match="workflow run"):
            get_workflow_id({})

    def test_an_empty_workflow_id_is_treated_as_missing(self) -> None:
        config: RunnableConfig = {"configurable": {"workflow_id": ""}}
        with pytest.raises(WorkflowConfigError, match="workflow run"):
            get_workflow_id(config)


@pytest.mark.unit
class TestGetUserId:
    def test_returns_the_configurable_user_id(self) -> None:
        config: RunnableConfig = {"configurable": {"user_id": "u1"}}
        assert get_user_id(config) == "u1"

    def test_a_config_without_a_user_raises(self) -> None:
        with pytest.raises(WorkflowConfigError, match="authentication"):
            get_user_id({"configurable": {}})


@pytest.mark.unit
class TestEditedTrigger:
    """The assistant re-emits the FULL workflow on every edit, so this decides
    what actually changed. Each of the three clauses is exercised alone: an
    ``and`` in place of any ``or`` here silently drops a real trigger edit."""

    def test_a_re_emitted_identical_trigger_is_not_reapplied(self) -> None:
        current = TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            trigger_name="daily_digest",
            timezone="Asia/Kolkata",
        )
        result = _edited_trigger(
            _draft(cron_expression="0 9 * * *", trigger_slug="daily_digest"),
            _workflow(current),
            "UTC",
        )
        assert result == (None, False)

    def test_a_type_only_change_is_applied_with_the_users_timezone(self) -> None:
        # Slug and cron come back byte-identical; only the type moved.
        current = TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression="0 9 * * *", timezone=None
        )
        config, needs_editor = _edited_trigger(
            _draft(trigger_type="manual", cron_expression="0 9 * * *"),
            _workflow(current),
            "America/New_York",
        )
        assert needs_editor is False
        assert config is not None
        assert config.type == TriggerType.MANUAL
        # No zone was ever authored, so the asking user's zone is the fallback.
        assert config.timezone == "America/New_York"

    def test_a_cron_only_change_rebuilds_the_whole_config(self) -> None:
        current = TriggerConfig(
            type=TriggerType.SCHEDULE,
            cron_expression="0 9 * * *",
            trigger_name="daily_digest",
            timezone="Asia/Kolkata",
        )
        config, needs_editor = _edited_trigger(
            _draft(cron_expression="0 8 * * *", trigger_slug="daily_digest"),
            _workflow(current, activated=False),
            "UTC",
        )
        assert needs_editor is False
        assert config is not None
        assert config.type == TriggerType.SCHEDULE
        # A paused workflow must not be re-enabled by a schedule edit.
        assert config.enabled is False
        assert config.cron_expression == "0 8 * * *"
        assert config.trigger_name == "daily_digest"
        # "Move it to 8am" means 8am where the workflow already runs.
        assert config.timezone == "Asia/Kolkata"

    def test_a_slug_only_change_on_an_integration_trigger_needs_the_editor(self) -> None:
        current = TriggerConfig(
            type=TriggerType.INTEGRATION, trigger_name="gmail_new_email", timezone="UTC"
        )
        result = _edited_trigger(
            _draft(trigger_type="integration", trigger_slug="gmail_new_labeled_email"),
            _workflow(current),
            "UTC",
        )
        # config_fields (labels, channels, repos) can't be set from here.
        assert result == (None, True)


@pytest.mark.unit
class TestRegeneratedAfterPromptEdit:
    """The update already committed, so regeneration is best-effort — but the
    call it makes and the warning it leaves behind are both load-bearing."""

    def _pieces(self) -> tuple[Workflow, Workflow]:
        current = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")
        return _workflow(current), _workflow(current, title="Morning digest — edited")

    async def test_regenerated_steps_replace_the_updated_workflow(self) -> None:
        workflow, updated = self._pieces()
        regenerated = _workflow(workflow.trigger_config, title="Regenerated")

        with patch(f"{SERVICE}.regenerate_workflow_steps", new_callable=AsyncMock) as mock_regen:
            mock_regen.return_value = regenerated
            result = await _regenerated_after_prompt_edit(workflow, USER_ID, updated)

        assert result is regenerated
        mock_regen.assert_awaited_once_with(
            workflow.id, USER_ID, regeneration_reason="prompt edited via assistant"
        )

    async def test_an_unsaved_workflow_regenerates_against_an_empty_id(self) -> None:
        workflow, updated = self._pieces()
        workflow = workflow.model_copy(update={"id": None})

        with patch(f"{SERVICE}.regenerate_workflow_steps", new_callable=AsyncMock) as mock_regen:
            mock_regen.return_value = None
            result = await _regenerated_after_prompt_edit(workflow, USER_ID, updated)

        mock_regen.assert_awaited_once_with(
            "", USER_ID, regeneration_reason="prompt edited via assistant"
        )
        # Nothing came back, so the committed update stands.
        assert result is updated

    async def test_a_regeneration_failure_keeps_the_update_and_is_reported(self) -> None:
        workflow, updated = self._pieces()

        with (
            patch(
                f"{SERVICE}.regenerate_workflow_steps",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch("app.utils.workflow_utils.log.warning") as warning,
        ):
            result = await _regenerated_after_prompt_edit(workflow, USER_ID, updated)

        assert result is updated
        warning.assert_called_once_with(
            f"{LogTag.WORKFLOW} Step regeneration after edit failed for",
            id=workflow.id,
            error="mongo down",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


@pytest.mark.unit
class TestApplyWorkflowEdit:
    async def test_a_trigger_only_edit_persists_just_the_trigger_config(self) -> None:
        current = TriggerConfig(
            type=TriggerType.SCHEDULE, cron_expression="0 9 * * *", timezone=None
        )
        workflow = _workflow(current)
        draft = _draft(cron_expression="0 8 * * *")
        writer = MagicMock()

        with patch(f"{SERVICE}.update_workflow", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = workflow
            await apply_workflow_edit(
                draft=draft, workflow=workflow, user_id=USER_ID, writer=writer
            )

        mock_update.assert_awaited_once()
        workflow_id, request, user_id = mock_update.await_args.args
        assert (workflow_id, user_id) == (workflow.id, USER_ID)
        # The default timezone reaches both the service call and the new config.
        assert mock_update.await_args.kwargs == {"user_timezone": "UTC"}
        # exclude_unset is what keeps a trigger edit from rewriting the prompt.
        assert set(request.model_dump(exclude_unset=True)) == {"trigger_config"}
        assert request.trigger_config is not None
        assert request.trigger_config.cron_expression == "0 8 * * *"
        assert request.trigger_config.timezone == "UTC"

    async def test_a_prompt_edit_regenerates_as_the_editing_user(self) -> None:
        """The regeneration must run under the user who edited the prompt; a
        dropped user_id would regenerate steps as nobody and fail auth checks."""
        current = TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")
        workflow = _workflow(current)
        draft = _draft(prompt="Summarize my inbox and my calendar")
        writer = MagicMock()

        with (
            patch(f"{SERVICE}.update_workflow", new_callable=AsyncMock) as mock_update,
            patch(f"{SERVICE}.regenerate_workflow_steps", new_callable=AsyncMock) as mock_regen,
        ):
            mock_update.return_value = workflow
            mock_regen.return_value = None
            await apply_workflow_edit(
                draft=draft, workflow=workflow, user_id=USER_ID, writer=writer
            )

        mock_regen.assert_awaited_once_with(
            workflow.id, USER_ID, regeneration_reason="prompt edited via assistant"
        )

    async def test_an_integration_trigger_change_alone_is_sent_to_the_editor(self) -> None:
        current = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="gmail_new_email")
        workflow = _workflow(current)
        draft = _draft(trigger_type="integration", trigger_slug="gmail_new_labeled_email")
        writer = MagicMock()

        with patch(f"{SERVICE}.update_workflow", new_callable=AsyncMock) as mock_update:
            result = await apply_workflow_edit(
                draft=draft, workflow=workflow, user_id=USER_ID, writer=writer
            )

        mock_update.assert_not_awaited()
        writer.assert_not_called()
        assert result == {
            "success": False,
            "error": "needs_editor",
            "message": (
                "Changing an integration trigger needs its config (channels, repos, "
                "calendars, etc.), which is set in the workflow editor in the app. Ask "
                "the user to adjust the trigger there."
            ),
        }


@pytest.mark.unit
class TestCreateWorkflowDirectly:
    async def test_the_card_description_is_not_the_execution_prompt(self) -> None:
        """description is card copy, prompt is the executor's goal. Writing the
        prompt into both put the whole numbered instruction blob, schedule
        preamble and all, on every chat-created workflow card."""
        draft = _draft(
            description="Priority-ordered digest of my unread Gmail",
            prompt=(
                "1. Use Gmail to fetch all unread emails\n"
                "2. Group them by how much they need my attention\n\n"
                "Expected output: a digest I can scan quickly."
            ),
            cron_expression="0 9 * * *",
        )
        writer = MagicMock()

        with patch(f"{SERVICE}.create_workflow", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _workflow(
                TriggerConfig(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *")
            )
            await create_workflow_directly(draft=draft, user_id=USER_ID, writer=writer)

        request = mock_create.await_args.kwargs["request"]
        assert request.description == "Priority-ordered digest of my unread Gmail"
        assert request.prompt == draft.prompt
        assert request.description != request.prompt

    async def test_a_draft_with_no_description_falls_back_to_the_title(self) -> None:
        draft = _draft(description="", prompt="Summarize my inbox")
        writer = MagicMock()

        with patch(f"{SERVICE}.create_workflow", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _workflow(TriggerConfig(type=TriggerType.MANUAL))
            await create_workflow_directly(draft=draft, user_id=USER_ID, writer=writer)

        request = mock_create.await_args.kwargs["request"]
        assert request.description == "Morning digest"
        assert request.prompt == "Summarize my inbox"

    async def test_a_draft_with_no_prompt_falls_back_to_the_description(self) -> None:
        """The description is the closest thing to instructions the assistant
        produced, so it beats the title. Only a draft missing both lands on the
        title."""
        draft = _draft(description="Summarize my unread Gmail", prompt="")
        writer = MagicMock()

        with patch(f"{SERVICE}.create_workflow", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = _workflow(TriggerConfig(type=TriggerType.MANUAL))
            await create_workflow_directly(draft=draft, user_id=USER_ID, writer=writer)

        request = mock_create.await_args.kwargs["request"]
        assert request.prompt == "Summarize my unread Gmail"
        assert request.description == "Summarize my unread Gmail"
