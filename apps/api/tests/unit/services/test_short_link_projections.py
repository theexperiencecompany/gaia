"""The public projections behind heygaia.link — what a recipient can see.

Each test feeds a stored document carrying the private fields a capability URL
must never serve (canvas Key Details, thread ids, addresses, todo ids, chat
bubbles) and asserts they are absent from the serialized public response.
Repositories are mocked at the seam; the projection logic is real.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.models.briefing_models import (
    BriefingItem,
    BriefingModel,
    BriefingPayload,
    BriefingSection,
)
from app.models.short_link_models import ShortLinkTargetType
from app.models.todo_models import TodoDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.short_link_projections import project_target
from app.services.tracked_todo_service import CANVAS_TEMPLATE

_MOD = "app.services.short_link_projections"

PRIVATE_EMAIL = "ceo@acme-secret.com"
PRIVATE_THREAD = "thread-18c2f9a"

CANVAS = (
    CANVAS_TEMPLATE.format(title="Reply to Acme")
    .replace(
        "## Key Details\n",
        f"## Key Details\n- email: {PRIVATE_EMAIL}\n- gmail thread: {PRIVATE_THREAD}\n",
    )
    .replace("## Current State\n", "## Current State\nDraft is ready for review.\n")
    .replace("## Activity Log\n", f"## Activity Log\n- read {PRIVATE_THREAD}\n")
    + "\n## Draft reply\nHi team, Tuesday works for us.\n"
)


class TestTodoDeliverable:
    async def test_serves_the_result_never_the_working_sections(self):
        todo = TodoDocument(id="t1", user_id="owner", title="Reply to Acme", canvas_content=CANVAS)
        with patch(f"{_MOD}.todo_repository") as repo:
            repo.get = AsyncMock(return_value=todo)
            view = await project_target(ShortLinkTargetType.TODO_DELIVERABLE, "owner", "t1")

        assert view is not None
        body = view.model_dump_json()
        assert "Draft is ready for review." in body
        assert "Tuesday works for us." in body
        for leaked in (PRIVATE_EMAIL, PRIVATE_THREAD, "Key Details", "<!--", '"t1"'):
            assert leaked not in body
        repo.get.assert_awaited_once_with("t1", user_id="owner")

    async def test_someone_elses_todo_projects_to_nothing(self):
        with patch(f"{_MOD}.todo_repository") as repo:
            repo.get = AsyncMock(return_value=None)
            assert await project_target(ShortLinkTargetType.TODO_DELIVERABLE, "x", "t1") is None


class TestBriefing:
    async def test_serves_the_brief_without_ids_or_chat_bubbles(self):
        briefing = BriefingModel(
            id="brief_abc",
            user_id="owner",
            date="2026-10-14",
            payload=BriefingPayload(
                kicker="Tuesday",
                date="Oct 14",
                headline="A clear day",
                lede="Two things moved.",
                sections=[
                    BriefingSection(
                        numeral="I",
                        title="Done",
                        items=[
                            BriefingItem(
                                text="Sent the Acme reply",
                                todo_id="todo-secret-id",
                                link="https://heygaia.link/xyz",
                            )
                        ],
                    )
                ],
                mood="clear",
                caption="See you tomorrow",
                message=f"hey, I emailed {PRIVATE_EMAIL}",
                bubbles=[f"hey, I emailed {PRIVATE_EMAIL}"],
            ),
        )
        with patch(f"{_MOD}.briefing_repository") as repo:
            repo.get = AsyncMock(return_value=briefing)
            view = await project_target(ShortLinkTargetType.BRIEFING, "owner", "brief_abc")

        assert view is not None
        body = view.model_dump_json()
        assert "Sent the Acme reply" in body
        for leaked in ("todo-secret-id", PRIVATE_EMAIL, "brief_abc", "owner"):
            assert leaked not in body
        repo.get.assert_awaited_once_with("brief_abc", user_id="owner")


class TestWorkflowRun:
    async def test_serves_status_and_summary_scoped_to_the_owner(self):
        execution = WorkflowExecutionDocument(
            execution_id="exec-1",
            workflow_id="wf-1",
            user_id="owner",
            status="success",
            started_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
            conversation_id="conv-secret",
            summary="Triaged 12 emails",
            error_message="internal stack trace",
        )
        workflow = AsyncMock()
        workflow.title = "Inbox triage"
        with (
            patch(f"{_MOD}.workflow_executions_repository") as executions,
            patch(f"{_MOD}.workflow_repository") as workflows,
        ):
            executions.get_for_user = AsyncMock(return_value=execution)
            workflows.get_for_user = AsyncMock(return_value=workflow)
            view = await project_target(ShortLinkTargetType.WORKFLOW_RUN, "owner", "exec-1")

        assert view is not None
        body = view.model_dump_json()
        assert "Triaged 12 emails" in body and "Inbox triage" in body
        for leaked in ("conv-secret", "internal stack trace", "wf-1", "exec-1"):
            assert leaked not in body
        executions.get_for_user.assert_awaited_once_with("exec-1", "owner")


class TestSessionArtifact:
    async def test_a_malformed_target_id_projects_to_nothing(self):
        with patch(f"{_MOD}.stat_artifact", AsyncMock()) as stat:
            view = await project_target(ShortLinkTargetType.SESSION_ARTIFACT, "owner", "no-path")
        assert view is None
        stat.assert_not_awaited()
