"""``WorkflowScheduler.execute_task`` is the BaseSchedulerService entry point.

Nothing calls it today (ARQ jobs call ``execute_workflow_by_id`` directly),
but the base class requires it, so the one implementation must be the real
fire: quota, execution record, playbook replay and notification all live in
``execute_workflow_by_id``. Calling ``execute_workflow_as_chat`` directly ran a
workflow with none of them.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_models import Workflow
from app.services.workflow.scheduler import WorkflowScheduler


@pytest.fixture
def scheduler() -> WorkflowScheduler:
    with patch(
        "app.services.scheduler_service.settings",
        MagicMock(REDIS_URL="redis://localhost:6379/0"),
    ):
        svc = WorkflowScheduler(redis_settings=MagicMock())
        svc.arq_pool = AsyncMock()
        return svc


@pytest.mark.unit
class TestExecuteTask:
    async def test_it_fires_the_workflow_through_the_real_entry_point(
        self, scheduler: WorkflowScheduler
    ) -> None:
        workflow = MagicMock(spec=Workflow)
        workflow.id = "wf_1"
        workflow.user_id = "u_1"
        by_id = AsyncMock(return_value="Workflow wf_1 executed successfully")
        as_chat = AsyncMock()

        with (
            patch("app.workers.tasks.execute_workflow_by_id", by_id),
            patch("app.workers.tasks.execute_workflow_as_chat", as_chat),
        ):
            result = await scheduler.execute_task(workflow)

        assert result.success is True
        # The fire's own message is the whole result: dropped, the scheduler
        # reports a success that says nothing about what ran.
        assert result.message == "Workflow wf_1 executed successfully"
        by_id.assert_awaited_once_with({}, "wf_1")
        as_chat.assert_not_awaited()

    async def test_a_non_workflow_task_is_refused(self, scheduler: WorkflowScheduler) -> None:
        result = await scheduler.execute_task(MagicMock())

        assert result.success is False
        assert "Workflow" in result.message
