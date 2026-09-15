"""The briefing system workflows: definitions, universal provisioning, playbook path.

Covers:
- definitions/briefing.py: keys, crons, is_system_workflow, schedule with no
  timezone (the provisioner stamps it), fresh step ids per factory call
- provisioner.provision_universal_system_workflows: idempotent by key, profile
  timezone stamped, silent when notify=False, "for you" title otherwise
- playbook/check.py asks a system workflow with these keys to author a playbook
  exactly as it asks a user workflow: nothing on that path reads
  is_system_workflow or system_workflow_key
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.prompts.briefing_prompts import DAILY_BRIEFING_PROMPT, WEEKLY_DIGEST_PROMPT
from app.agents.prompts.playbook_prompts import PLAYBOOK_CHECK_BRIEF
from app.constants.briefing import (
    BRIEFING_DAILY_CRON,
    BRIEFING_DAILY_KEY,
    BRIEFING_WEEKLY_CRON,
    BRIEFING_WEEKLY_KEY,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowDocument,
)
from app.services.system_workflows.definitions.briefing import BRIEFING_SYSTEM_WORKFLOWS
from app.services.system_workflows.provisioner import (
    SYSTEM_WORKFLOW_REGISTRY,
    UNIVERSAL_SYSTEM_WORKFLOWS,
    provision_universal_system_workflows,
)
from app.services.workflow.playbook.check import playbook_check_brief

# The two definitions, field for field. These workflows ship to every user at
# onboarding and nothing downstream re-derives their text, so the text IS the
# feature: a typo in a step description is a shipped bug that no other test in
# the suite would notice.
EXPECTED_DEFINITIONS: dict[str, dict[str, object]] = {
    BRIEFING_DAILY_KEY: {
        "title": "Daily Briefing",
        "description": (
            "Every morning: today's meetings, what is waiting on you, and what moved, "
            "read from the integrations you have connected."
        ),
        "prompt": DAILY_BRIEFING_PROMPT,
        "cron": BRIEFING_DAILY_CRON,
        "steps": [
            (
                "Read today from each connected integration",
                "gaia",
                "One fixed read-only call per connected integration, in order: "
                "calendar events today, inbox threads from the last 24 hours, "
                "pull requests, issues, pages, mentions from the last 24 hours, "
                "and todos due today. Nothing for integrations that are not connected.",
            ),
            (
                "Write the briefing",
                "gaia",
                "Plain text, at most 12 lines: the shape of the day, what is waiting "
                "on the user, what moved. One or two lines on an empty day. "
                "A final 'Next:' line naming one thing GAIA could do that it is not yet.",
            ),
        ],
    },
    BRIEFING_WEEKLY_KEY: {
        "title": "Weekly Digest",
        "description": (
            "Sunday evening: the receipt for the week, numbers first, "
            "what GAIA did and what you did across your connected integrations."
        ),
        "prompt": WEEKLY_DIGEST_PROMPT,
        "cron": BRIEFING_WEEKLY_CRON,
        "steps": [
            (
                "Read the week from GAIA and each connected integration",
                "gaia",
                "Workflow and todo statistics, then one fixed read-only call per "
                "connected integration over the last 7 days, in order. "
                "Nothing for integrations that are not connected.",
            ),
            (
                "Write the digest",
                "gaia",
                "The fixed WEEK OF / GAIA / YOU / NOTABLE / NEXT shape, counts before "
                "words, one YOU line per connected integration.",
            ),
        ],
    },
}

PROVISIONER = "app.services.system_workflows.provisioner"
CHECK = "app.services.workflow.playbook.check"
USER_ID = "user-1"


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{PROVISIONER}.log"):
        yield


def _definitions() -> dict[str, CreateWorkflowRequest]:
    return {key: factory() for key, factory in BRIEFING_SYSTEM_WORKFLOWS}


class TestBriefingDefinitions:
    def test_keys_and_crons(self) -> None:
        defs = _definitions()
        assert set(defs) == {BRIEFING_DAILY_KEY, BRIEFING_WEEKLY_KEY}
        assert BRIEFING_DAILY_KEY == "briefing:daily"
        assert BRIEFING_WEEKLY_KEY == "briefing:weekly"
        assert defs[BRIEFING_DAILY_KEY].trigger_config.cron_expression == BRIEFING_DAILY_CRON
        assert defs[BRIEFING_WEEKLY_KEY].trigger_config.cron_expression == BRIEFING_WEEKLY_CRON
        assert BRIEFING_DAILY_CRON == "0 8 * * *"
        assert BRIEFING_WEEKLY_CRON.split()[-1] == "0", "weekly digest fires on Sunday"

    def test_system_schedule_without_timezone(self) -> None:
        for key, request in _definitions().items():
            assert request.is_system_workflow is True, key
            assert request.system_workflow_key == key
            assert request.source_integration is None, "not owned by an integration"
            assert request.trigger_config.type == TriggerType.SCHEDULE
            assert request.trigger_config.timezone is None, "the provisioner stamps it"
            assert request.trigger_config.enabled is True, "provisioned already armed"
            assert request.steps and all(step.id for step in request.steps)

    def test_each_factory_call_mints_fresh_step_ids(self) -> None:
        for _key, factory in BRIEFING_SYSTEM_WORKFLOWS:
            first = {step.id for step in factory().steps or []}
            second = {step.id for step in factory().steps or []}
            assert first.isdisjoint(second)

    @pytest.mark.parametrize("key", [BRIEFING_DAILY_KEY, BRIEFING_WEEKLY_KEY])
    def test_definition_content_is_pinned(self, key: str) -> None:
        expected = EXPECTED_DEFINITIONS[key]
        request = _definitions()[key]

        assert request.title == expected["title"]
        assert request.description == expected["description"]
        assert request.prompt is expected["prompt"], "the prompt is the product"
        assert request.trigger_config.cron_expression == expected["cron"]

        steps = request.steps or []
        assert [(s.title, s.category, s.description) for s in steps] == expected["steps"]

    def test_universal_set_is_exactly_the_two_briefings_in_order(self) -> None:
        assert [key for key, _ in BRIEFING_SYSTEM_WORKFLOWS] == [
            BRIEFING_DAILY_KEY,
            BRIEFING_WEEKLY_KEY,
        ]

    def test_universal_set_and_registry(self) -> None:
        assert UNIVERSAL_SYSTEM_WORKFLOWS == BRIEFING_SYSTEM_WORKFLOWS
        assert BRIEFING_DAILY_KEY in SYSTEM_WORKFLOW_REGISTRY, "reset-to-default must find it"
        assert BRIEFING_WEEKLY_KEY in SYSTEM_WORKFLOW_REGISTRY


class TestProvisionUniversalSystemWorkflows:
    @pytest.mark.asyncio
    @patch(f"{PROVISIONER}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.get_user_by_id", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.WorkflowService")
    @patch(f"{PROVISIONER}.workflow_repository")
    async def test_creates_both_stamped_with_profile_timezone(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_get_user: AsyncMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": " Asia/Kolkata "}

        created = await provision_universal_system_workflows(USER_ID, notify=False)

        assert {r.system_workflow_key for r in created} == {
            BRIEFING_DAILY_KEY,
            BRIEFING_WEEKLY_KEY,
        }
        assert mock_workflow_svc.create_workflow.await_count == 2
        for call in mock_workflow_svc.create_workflow.await_args_list:
            request, user_id = call.args
            assert user_id == USER_ID
            assert request.trigger_config.timezone == "Asia/Kolkata"
        mock_get_user.assert_awaited_once_with(USER_ID)
        mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{PROVISIONER}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.get_user_by_id", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.WorkflowService")
    @patch(f"{PROVISIONER}.workflow_repository")
    async def test_idempotent_only_creates_missing_key(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_get_user: AsyncMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(
            side_effect=lambda _uid, key: MagicMock() if key == BRIEFING_DAILY_KEY else None
        )
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": ""}

        created = await provision_universal_system_workflows(USER_ID)

        assert [r.system_workflow_key for r in created] == [BRIEFING_WEEKLY_KEY]
        (request, _), _ = mock_workflow_svc.create_workflow.await_args
        assert request.trigger_config.timezone == "UTC", "blank profile timezone falls back"
        mock_notify.assert_awaited_once_with(USER_ID, None, created)

    @pytest.mark.asyncio
    @patch(f"{PROVISIONER}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.get_user_by_id", new_callable=AsyncMock)
    @patch(f"{PROVISIONER}.WorkflowService")
    @patch(f"{PROVISIONER}.workflow_repository")
    async def test_nothing_missing_creates_and_notifies_nothing(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_get_user: AsyncMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=MagicMock())
        mock_workflow_svc.create_workflow = AsyncMock()

        assert await provision_universal_system_workflows(USER_ID) == []

        mock_workflow_svc.create_workflow.assert_not_awaited()
        mock_get_user.assert_not_awaited()
        mock_notify.assert_not_awaited()


class TestUniversalNotificationTitle:
    @pytest.mark.asyncio
    @patch(f"{PROVISIONER}.NotificationService")
    async def test_title_addresses_the_user_not_an_integration(
        self, mock_notif_cls: MagicMock
    ) -> None:
        from app.services.system_workflows.provisioner import _notify_workflows_provisioned

        mock_svc = AsyncMock()
        mock_notif_cls.return_value = mock_svc

        await _notify_workflows_provisioned(
            USER_ID, None, [f() for _, f in BRIEFING_SYSTEM_WORKFLOWS]
        )

        notification = mock_svc.create_notification.call_args[0][0]
        assert notification.content.title == "I set up 2 workflows for you"


class TestPlaybookPathAsksSystemWorkflows:
    """The playbook check gates on playbook state and decline count only.

    A briefing workflow document carries is_system_workflow=True and one of the
    briefing keys; the check must still hand back the check brief, the same as
    it does for a user workflow (test_playbook_check.py).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", [BRIEFING_DAILY_KEY, BRIEFING_WEEKLY_KEY])
    async def test_check_brief_for_system_workflow(self, key: str) -> None:
        request = SYSTEM_WORKFLOW_REGISTRY[key]()
        document = WorkflowDocument(
            id="wf-briefing",
            user_id=USER_ID,
            title=request.title,
            prompt=request.prompt,
            steps=request.steps or [],
            trigger_config=TriggerConfig(
                type=TriggerType.SCHEDULE,
                cron_expression=request.trigger_config.cron_expression,
                enabled=True,
            ),
            is_system_workflow=True,
            system_workflow_key=key,
        )
        with (
            patch(f"{CHECK}.playbook_repository.get_for_workflow", AsyncMock(return_value=None)),
            patch(f"{CHECK}.workflow_repository.get_for_user", AsyncMock(return_value=document)),
        ):
            assert await playbook_check_brief("wf-briefing", USER_ID) == PLAYBOOK_CHECK_BRIEF
