"""The public projections behind heygaia.link — what a recipient can see.

Each test feeds a stored document carrying the private fields a capability URL
must never serve (canvas Key Details, thread ids, addresses, todo ids, chat
bubbles) and asserts they are absent from the serialized public response.
Repositories are mocked at the seam; the projection logic is real.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.constants.briefing import BriefOutcome
from app.models.briefing_models import (
    BriefingEvent,
    BriefingItem,
    BriefingModel,
    BriefingPayload,
    BriefingSection,
)
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.models.short_link_models import (
    PublicBriefing,
    PublicBriefingEvent,
    PublicBriefingItem,
    PublicBriefingPayload,
    PublicBriefingSection,
    PublicOpenUIArtifact,
    PublicSessionArtifact,
    PublicTodoDeliverable,
    PublicWorkflowRun,
    ShortLinkTargetType,
)
from app.models.todo_models import TodoDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.canvas_markdown import deliverable_markdown
from app.services.short_link_projections import (
    PUBLIC_TEXT_MAX_BYTES,
    project_target,
    target_file,
)
from app.services.storage import ArtifactInfo
from app.services.tracked_todo_service import CANVAS_TEMPLATE

_MOD = "app.services.short_link_projections"

PRIVATE_EMAIL = "ceo@acme-secret.com"
PRIVATE_THREAD = "thread-18c2f9a"
SESSION = ShortLinkTargetType.SESSION_ARTIFACT

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
        assert view == PublicTodoDeliverable(
            target_type=ShortLinkTargetType.TODO_DELIVERABLE,
            title="Reply to Acme",
            completed=False,
            content=deliverable_markdown(CANVAS),
        )

    async def test_a_todo_with_no_canvas_serves_an_empty_result(self):
        todo = TodoDocument(id="t1", user_id="owner", title="Call mum", canvas_content=None)
        with patch(f"{_MOD}.todo_repository") as repo:
            repo.get = AsyncMock(return_value=todo)
            view = await project_target(ShortLinkTargetType.TODO_DELIVERABLE, "owner", "t1")

        assert view is not None
        assert view.content == ""

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
            edition_image_url="https://cdn.heygaia.io/editions/brief.png",
            payload=BriefingPayload(
                kicker="Tuesday",
                template_family="swiss",
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
                                outcome=BriefOutcome.SENT,
                                todo_id="todo-secret-id",
                                link="https://heygaia.link/xyz",
                            )
                        ],
                    )
                ],
                mood="clear",
                caption="See you tomorrow",
                calendar=[
                    BriefingEvent(
                        date="2026-10-14", start="09:30", title="Standup", location="Room 4B"
                    )
                ],
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
        for leaked in ("todo-secret-id", PRIVATE_EMAIL, "brief_abc", "owner", "Room 4B"):
            assert leaked not in body
        repo.get.assert_awaited_once_with("brief_abc", user_id="owner")
        assert view == PublicBriefing(
            target_type=ShortLinkTargetType.BRIEFING,
            kind=briefing.kind,
            edition_image_url="https://cdn.heygaia.io/editions/brief.png",
            payload=PublicBriefingPayload(
                kicker="Tuesday",
                date="Oct 14",
                headline="A clear day",
                lede="Two things moved.",
                stats=briefing.payload.stats,
                sections=[
                    PublicBriefingSection(
                        numeral="I",
                        title="Done",
                        items=[
                            PublicBriefingItem(
                                text="Sent the Acme reply",
                                kind="note",
                                link="https://heygaia.link/xyz",
                            )
                        ],
                    )
                ],
                mood="clear",
                caption="See you tomorrow",
                hue=briefing.payload.hue,
                calendar=[PublicBriefingEvent(date="2026-10-14", start="09:30", title="Standup")],
            ),
        )

    async def test_someone_elses_brief_projects_to_nothing(self):
        with patch(f"{_MOD}.briefing_repository") as repo:
            repo.get = AsyncMock(return_value=None)
            assert await project_target(ShortLinkTargetType.BRIEFING, "x", "brief_abc") is None


class TestWorkflowRun:
    async def test_serves_status_and_summary_scoped_to_the_owner(self):
        execution = WorkflowExecutionDocument(
            execution_id="exec-1",
            workflow_id="wf-1",
            user_id="owner",
            status="success",
            started_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
            completed_at=datetime(2026, 10, 14, 8, 5, tzinfo=UTC),
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
        workflows.get_for_user.assert_awaited_once_with("wf-1", "owner")
        assert view == PublicWorkflowRun(
            target_type=ShortLinkTargetType.WORKFLOW_RUN,
            workflow_title="Inbox triage",
            status="success",
            started_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
            completed_at=datetime(2026, 10, 14, 8, 5, tzinfo=UTC),
            summary="Triaged 12 emails",
        )

    async def test_a_run_whose_workflow_is_gone_projects_to_nothing(self):
        execution = WorkflowExecutionDocument(
            execution_id="exec-1",
            workflow_id="wf-1",
            user_id="owner",
            status="success",
            started_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
        )
        with (
            patch(f"{_MOD}.workflow_executions_repository") as executions,
            patch(f"{_MOD}.workflow_repository") as workflows,
        ):
            executions.get_for_user = AsyncMock(return_value=execution)
            workflows.get_for_user = AsyncMock(return_value=None)
            view = await project_target(ShortLinkTargetType.WORKFLOW_RUN, "owner", "exec-1")

        assert view is None


class TestWorkflowRunStillFinishing:
    async def test_a_run_not_yet_completed_reads_as_running(self):
        """A run not yet marked complete reads as running, never as a finished run."""
        execution = WorkflowExecutionDocument(
            execution_id="exec-1",
            workflow_id="wf-1",
            user_id="owner",
            status="running",
            started_at=datetime(2026, 10, 14, 8, tzinfo=UTC),
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
        assert view.status == "running"
        assert view.completed_at is None
        assert view.summary == ""


def _info(path: str, *, size: int, content_type: str | None) -> ArtifactInfo:
    return ArtifactInfo(path=path, size_bytes=size, mtime=0.0, content_type=content_type)


@pytest.fixture
def workspace(tmp_path):
    """Patch the artifact storage seam onto one file on disk; yields (file, stat, resolve)."""
    host_file = tmp_path / "q3.html"
    with (
        patch(f"{_MOD}.stat_artifact", AsyncMock()) as stat,
        patch(f"{_MOD}.resolve_session_path", AsyncMock(return_value=host_file)) as resolve,
    ):
        yield host_file, stat, resolve


class TestEscapingTargetIds:
    """A target id that leaves the owner's artifacts root names no artifact: not a crash.

    Runs the real storage walk over a tmp mount, so the containment check that
    raises is the production one.
    """

    @pytest.fixture(autouse=True)
    def mount(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
        monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
        (tmp_path / "secret.txt").write_text("not yours")

    @pytest.mark.parametrize(
        "target_id", ["conv-1/../../../../secret.txt", "conv-1/../../other-user/x", "..%2f/x"]
    )
    async def test_projects_to_nothing(self, target_id: str) -> None:
        assert await project_target(SESSION, "owner", target_id) is None

    async def test_the_public_file_route_finds_nothing(self) -> None:
        assert await target_file(SESSION, "owner", "conv-1/../../../../secret.txt") is None


class TestSessionArtifact:
    @pytest.mark.parametrize("target_id", ["no-path", "conv-1/", "/reports/q3.html"])
    async def test_a_malformed_target_id_projects_to_nothing(self, target_id):
        with patch(f"{_MOD}.stat_artifact", AsyncMock()) as stat:
            view = await project_target(SESSION, "owner", target_id)
        assert view is None
        stat.assert_not_awaited()

    async def test_a_text_file_ships_its_contents_read_from_the_owners_workspace(self, workspace):
        host_file, stat, resolve = workspace
        host_file.write_bytes("<h1>Q3 — done</h1>".encode() + bytes([0xFF]))
        stat.return_value = _info("reports/q3.html", size=12, content_type="text/html")

        view = await project_target(SESSION, "owner", "conv-1/reports/q3.html")

        assert view == PublicSessionArtifact(
            target_type=SESSION,
            filename="q3.html",
            content_type="text/html",
            size_bytes=12,
            content="<h1>Q3 — done</h1>\N{REPLACEMENT CHARACTER}",
        )
        stat.assert_awaited_once_with("owner", "conv-1", "reports/q3.html")
        resolve.assert_awaited_once_with("owner", "conv-1", "artifacts", "reports/q3.html")

    async def test_a_text_file_at_exactly_the_cap_still_ships_inline(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_text("body")
        stat.return_value = _info("q3.html", size=PUBLIC_TEXT_MAX_BYTES, content_type="text/html")

        view = await project_target(SESSION, "owner", "conv-1/q3.html")

        assert view is not None
        assert view.content == "body"

    async def test_a_text_file_over_the_cap_is_a_metadata_card(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_text("body")
        stat.return_value = _info(
            "q3.html", size=PUBLIC_TEXT_MAX_BYTES + 1, content_type="text/html"
        )

        view = await project_target(SESSION, "owner", "conv-1/q3.html")

        assert view is not None
        assert view.content is None

    async def test_a_binary_file_is_a_metadata_card_never_its_bytes(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_bytes(b"%PDF-1.7")
        stat.return_value = _info("deck.pdf", size=8, content_type="application/pdf")

        view = await project_target(SESSION, "owner", "conv-1/deck.pdf")

        assert view is not None
        assert view.content is None
        assert view.content_type == "application/pdf"

    async def test_an_untyped_file_is_served_as_opaque_bytes(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_bytes(b"\x00")
        stat.return_value = _info("blob", size=1, content_type=None)

        view = await project_target(SESSION, "owner", "conv-1/blob")

        assert view is not None
        assert view.content_type == "application/octet-stream"
        assert view.content is None

    async def test_a_deleted_file_projects_to_nothing(self, workspace):
        _, stat, resolve = workspace
        stat.return_value = None

        assert await project_target(SESSION, "owner", "conv-1/q3.html") is None
        assert await target_file(SESSION, "owner", "conv-1/q3.html") is None
        resolve.assert_not_awaited()

    async def test_the_public_file_route_streams_the_owners_host_file(self, workspace):
        host_file, stat, resolve = workspace
        stat.return_value = _info("reports/q3.html", size=1, content_type="text/html")

        assert await target_file(SESSION, "owner", "conv-1/reports/q3.html") == host_file
        resolve.assert_awaited_once_with("owner", "conv-1", "artifacts", "reports/q3.html")

    @pytest.mark.parametrize(
        "target_type",
        [t for t in ShortLinkTargetType if t is not ShortLinkTargetType.SESSION_ARTIFACT],
    )
    async def test_a_target_type_with_no_bytes_has_no_file(self, workspace, target_type):
        _, stat, resolve = workspace

        assert await target_file(target_type, "owner", "conv-1/q3.html") is None
        stat.assert_not_awaited()
        resolve.assert_not_awaited()


class TestOpenUIArtifact:
    async def test_serves_the_program_and_the_owners_name_never_their_email(self):
        artifact = OpenUIArtifact(
            id="a1",
            user_id="owner",
            conversation_id="conv-secret",
            kind=ArtifactKind.REPORT,
            title="Pilot",
            program='root = Artifact("Pilot", "s", [], [])',
            brief_hash="brief-secret",
            model="gpt-6-luna",
        )
        owner = AsyncMock()
        owner.name = "Maya Chen"
        owner.email = "maya@example.com"
        with (
            patch(f"{_MOD}.openui_artifact_repository") as artifacts,
            patch(f"{_MOD}.user_repository") as users,
        ):
            artifacts.get = AsyncMock(return_value=artifact)
            users.get = AsyncMock(return_value=owner)
            view = await project_target(ShortLinkTargetType.OPENUI_ARTIFACT, "owner", "a1")

        assert isinstance(view, PublicOpenUIArtifact)
        assert (view.shared_by, view.program) == ("Maya Chen", artifact.program)
        body = view.model_dump_json()
        for leaked in ("maya@example.com", "conv-secret", "brief-secret", "owner"):
            assert leaked not in body
        artifacts.get.assert_awaited_once_with("a1", user_id="owner")

    async def test_someone_elses_artifact_projects_to_nothing(self):
        with patch(f"{_MOD}.openui_artifact_repository") as artifacts:
            artifacts.get = AsyncMock(return_value=None)
            assert await project_target(ShortLinkTargetType.OPENUI_ARTIFACT, "x", "a1") is None
