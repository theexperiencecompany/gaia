"""The link target specs' projections — what a recipient of a heygaia.link can see.

Each test feeds a stored document carrying the private fields a capability URL
must never serve (canvas Key Details, thread ids, addresses, todo ids, the chat
message) and asserts they are absent from the serialized public response.
Repositories are mocked at the seam; the projection logic is real.
"""

from datetime import UTC, datetime
from typing import Final
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import settings
from app.constants.briefing import BriefOutcome, EditionFamily
from app.constants.short_links import MAX_SNAPSHOT_BYTES, MAX_VIEW_TEXT_BYTES
from app.db.repositories.short_links import short_link_repository
from app.models.brief_document_models import BriefingModel, EditionRender
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
)
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact
from app.models.short_link_models import (
    LinkAccess,
    LinkSnapshot,
    LinkTarget,
    LinkViewerKind,
    PublicBriefing,
    PublicOpenUIArtifact,
    PublicTodoDeliverable,
    PublicWorkflowRun,
    PublicWorkspaceFile,
    RecordTarget,
    RecordTargetType,
    RenderMode,
    ShortLink,
    ShortLinkTargetType,
    WorkspaceFileTarget,
)
from app.models.todo_models import TodoDocument
from app.models.workflow_execution_models import WorkflowExecutionDocument
from app.services.canvas_markdown import deliverable_markdown
from app.services.links.registry import REGISTRY
from app.services.links.spec import PreviewFacts, SnapshotSource
from app.services.storage import ArtifactInfo, JuiceFSUnavailable
from app.services.tracked_todo_service import CANVAS_TEMPLATE
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

PRIVATE_EMAIL = "ceo@acme-secret.com"
PRIVATE_THREAD = "thread-18c2f9a"
FILE: Final = ShortLinkTargetType.WORKSPACE_FILE


def _file(path: str, conversation_id: str = "conv-1") -> WorkspaceFileTarget:
    return WorkspaceFileTarget(type=FILE, conversation_id=conversation_id, path=path)


def _link(
    target: LinkTarget,
    owner_id: str,
    snapshot: LinkSnapshot | None = None,
    access: LinkAccess = LinkAccess.UNLISTED,
) -> ShortLink:
    return ShortLink(
        slug="abcdefghijk", user_id=owner_id, target=target, snapshot=snapshot, access=access
    )


async def _project(
    target_type: RecordTargetType,
    owner_id: str,
    target_id: str,
    viewer: LinkViewerKind = LinkViewerKind.RECIPIENT,
) -> object:
    link = _link(RecordTarget(type=target_type, id=target_id), owner_id)
    return await REGISTRY[target_type].project(link, link.target, viewer)


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
        with patch("app.services.links.targets.todo_deliverable.todo_repository") as repo:
            repo.get = AsyncMock(return_value=todo)
            view = await _project(ShortLinkTargetType.TODO_DELIVERABLE, "owner", "t1")

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
        with patch("app.services.links.targets.todo_deliverable.todo_repository") as repo:
            repo.get = AsyncMock(return_value=todo)
            view = await _project(ShortLinkTargetType.TODO_DELIVERABLE, "owner", "t1")

        assert view is not None
        assert view.content == ""

    async def test_someone_elses_todo_projects_to_nothing(self):
        with patch("app.services.links.targets.todo_deliverable.todo_repository") as repo:
            repo.get = AsyncMock(return_value=None)
            assert await _project(ShortLinkTargetType.TODO_DELIVERABLE, "x", "t1") is None


def _brief_with_items(*todo_ids: str) -> BriefingModel:
    return BriefingModel(
        id="brief_abc",
        user_id="owner",
        date="2026-10-14",
        payload=BriefingPayload(
            kicker="Tuesday",
            template_family=EditionFamily.SWISS,
            date="Oct 14",
            headline="A clear day",
            lede="Two things moved.",
            sections=[
                BriefingSection(
                    numeral="I",
                    title="Done",
                    items=[
                        BriefingItem(
                            text=f"Item {todo_id}",
                            outcome=BriefOutcome.SENT,
                            todo_id=todo_id,
                            link=f"https://heygaia.link/old-{todo_id}",
                        )
                        for todo_id in todo_ids
                    ],
                )
            ],
            mood=BriefingMood.CLEAR,
            caption="See you tomorrow",
        ),
    )


BRIEF = RecordTarget(type=ShortLinkTargetType.BRIEFING, id="brief_abc")


class TestBriefing:
    async def test_a_brief_previews_by_its_headline_on_a_generated_card(self):
        brief = _brief_with_items()
        brief.edition = EditionRender(key="edition-key")
        with patch("app.services.links.targets.briefing.briefing_repository") as repo:
            repo.get = AsyncMock(return_value=brief)
            facts = await REGISTRY[ShortLinkTargetType.BRIEFING].preview("owner", BRIEF, None)

        assert facts == PreviewFacts(title=brief.payload.headline, image_url=None)
        repo.get.assert_awaited_once_with("brief_abc", user_id="owner")

    @pytest.mark.parametrize("viewer", list(LinkViewerKind))
    async def test_serves_the_front_page_alone_to_every_viewer(self, viewer: LinkViewerKind):
        briefing = BriefingModel(
            id="brief_abc",
            user_id="owner",
            date="2026-10-14",
            edition=EditionRender(key="edition-key"),
            payload=BriefingPayload(
                kicker="Tuesday",
                template_family=EditionFamily.SWISS,
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
                mood=BriefingMood.CLEAR,
                caption="See you tomorrow",
                calendar=[
                    BriefingEvent(
                        date="2026-10-14", start="09:30", title="Standup", location="Room 4B"
                    )
                ],
                message=f"hey, I emailed {PRIVATE_EMAIL}",
            ),
        )
        with patch("app.services.links.targets.briefing.briefing_repository") as repo:
            repo.get = AsyncMock(return_value=briefing)
            view = await _project(ShortLinkTargetType.BRIEFING, "owner", "brief_abc", viewer)

        repo.get.assert_awaited_once_with("brief_abc", user_id="owner")
        assert view == PublicBriefing(
            target_type=ShortLinkTargetType.BRIEFING,
            kind=briefing.kind,
            kicker="Tuesday",
            date="Oct 14",
            headline="A clear day",
        )

    async def test_someone_elses_brief_projects_to_nothing(self):
        with patch("app.services.links.targets.briefing.briefing_repository") as repo:
            repo.get = AsyncMock(return_value=None)
            assert await _project(ShortLinkTargetType.BRIEFING, "x", "brief_abc") is None


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
            patch(
                "app.services.links.targets.workflow_run.workflow_executions_repository"
            ) as executions,
            patch("app.services.links.targets.workflow_run.workflow_repository") as workflows,
        ):
            executions.get_for_user = AsyncMock(return_value=execution)
            workflows.get_for_user = AsyncMock(return_value=workflow)
            view = await _project(ShortLinkTargetType.WORKFLOW_RUN, "owner", "exec-1")

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
            patch(
                "app.services.links.targets.workflow_run.workflow_executions_repository"
            ) as executions,
            patch("app.services.links.targets.workflow_run.workflow_repository") as workflows,
        ):
            executions.get_for_user = AsyncMock(return_value=execution)
            workflows.get_for_user = AsyncMock(return_value=None)
            view = await _project(ShortLinkTargetType.WORKFLOW_RUN, "owner", "exec-1")

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
            patch(
                "app.services.links.targets.workflow_run.workflow_executions_repository"
            ) as executions,
            patch("app.services.links.targets.workflow_run.workflow_repository") as workflows,
        ):
            executions.get_for_user = AsyncMock(return_value=execution)
            workflows.get_for_user = AsyncMock(return_value=workflow)
            view = await _project(ShortLinkTargetType.WORKFLOW_RUN, "owner", "exec-1")

        assert view is not None
        assert view.status == "running"
        assert view.completed_at is None
        assert view.summary == ""


def _info(path: str, *, size: int, content_type: str | None) -> ArtifactInfo:
    return ArtifactInfo(path=path, size_bytes=size, mtime=0.0, content_type=content_type)


_FILE_MOD = "app.services.links.targets.workspace_file"


async def _source(owner_id: str, target: WorkspaceFileTarget) -> SnapshotSource | None:
    read = REGISTRY[FILE].source
    assert read is not None
    return await read(owner_id, target)


@pytest.fixture
def workspace(tmp_path):
    """Patch the artifact storage seam onto one file on disk; yields (file, stat, resolve)."""
    host_file = tmp_path / "q3.html"
    with (
        patch(f"{_FILE_MOD}.stat_artifact", AsyncMock()) as stat,
        patch(f"{_FILE_MOD}.resolve_session_path", AsyncMock(return_value=host_file)) as resolve,
    ):
        yield host_file, stat, resolve


class TestEscapingPaths:
    """A path that leaves the conversation's workspace files names no file: not a crash.

    Runs the real storage walk over a tmp mount, so the containment check that
    raises is the production one.
    """

    @pytest.fixture(autouse=True)
    def mount(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
        monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
        (tmp_path / "secret.txt").write_text("not yours")

    @pytest.mark.parametrize(
        ("conversation_id", "path"),
        [("conv-1", "../../../../secret.txt"), ("conv-1", "../../other-user/x")],
    )
    async def test_reads_nothing(self, conversation_id: str, path: str) -> None:
        assert await _source("owner", _file(path, conversation_id)) is None


class TestWorkspaceFileSource:
    """The live file is read only to publish a snapshot of it."""

    async def test_reads_the_owners_bytes_and_declared_type(self, workspace):
        host_file, stat, resolve = workspace
        host_file.write_bytes(b"<h1>Q3</h1>")
        stat.return_value = _info("reports/q3.html", size=11, content_type="text/html")

        source = await _source("owner", _file("reports/q3.html"))

        assert source == SnapshotSource(
            filename="q3.html", declared_mime="text/html", size_bytes=11, data=b"<h1>Q3</h1>"
        )
        stat.assert_awaited_once_with("owner", "conv-1", "reports/q3.html")
        resolve.assert_awaited_once_with("owner", "conv-1", "artifacts", "reports/q3.html")

    async def test_a_file_at_the_cap_is_read(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_bytes(b"x")
        stat.return_value = _info("q3.html", size=MAX_SNAPSHOT_BYTES, content_type="text/html")

        source = await _source("owner", _file("q3.html"))

        assert source is not None
        assert source.data == b"x"

    async def test_a_file_over_the_cap_is_never_read(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_bytes(b"x")
        stat.return_value = _info("q3.html", size=MAX_SNAPSHOT_BYTES + 1, content_type="text/html")

        source = await _source("owner", _file("q3.html"))

        assert source is not None
        assert source.data is None
        assert source.size_bytes == MAX_SNAPSHOT_BYTES + 1

    async def test_an_untyped_file_declares_opaque_bytes(self, workspace):
        host_file, stat, _ = workspace
        host_file.write_bytes(b"\x00")
        stat.return_value = _info("blob", size=1, content_type=None)

        source = await _source("owner", _file("blob"))

        assert source is not None
        assert source.declared_mime == "application/octet-stream"

    async def test_a_deleted_file_reads_nothing(self, workspace):
        _, stat, resolve = workspace
        stat.return_value = None

        assert await _source("owner", _file("q3.html")) is None
        resolve.assert_not_awaited()

    async def test_workspace_storage_offline_is_a_503_not_a_missing_file(self, workspace):
        _, stat, _ = workspace
        outage = JuiceFSUnavailable("mount gone")
        stat.side_effect = outage

        with pytest.raises(AppError) as raised:
            await _source("owner", _file("q3.html"))

        error = raised.value
        assert (error.message, error.fix, error.status_code, error.code) == (
            "Workspace storage is offline, so this file can't be shared right now",
            "Try again in a minute",
            503,
            "workspace_storage_offline",
        )
        assert error.__cause__ is outage

    @pytest.mark.parametrize("target_type", [t for t in ShortLinkTargetType if t is not FILE])
    def test_no_other_type_serves_bytes(self, target_type):
        assert REGISTRY[target_type].source is None


class TestWorkspaceFilesInAConversation:
    def test_are_read_from_the_conversations_live_links(self):
        assert REGISTRY[FILE].in_conversation == short_link_repository.live_workspace_files_in


def _snapshot(**overrides: object) -> LinkSnapshot:
    data: dict[str, object] = {
        "filename": "notes.md",
        "mime": "text/markdown",
        "size_bytes": 5,
        "render": RenderMode.TEXT,
        "content_id": "a" * 26,
    }
    data.update(overrides)
    return LinkSnapshot.model_validate(data)


class TestWorkspaceFileProjection:
    """Opening a file link reads the pinned snapshot, never the live file."""

    @pytest.fixture
    def stored(self):
        with patch(f"{_FILE_MOD}.read_snapshot", AsyncMock(return_value=b"# Hi\xff")) as read:
            yield read

    @pytest.fixture
    def no_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", None)

    @pytest.fixture
    def origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LINK_CONTENT_URL_TEMPLATE", "https://{content_id}.u.test")
        monkeypatch.setattr(settings, "LINK_CONTENT_SIGNING_KEY", "k" * 32)

    async def _view(self, snapshot: LinkSnapshot | None) -> PublicWorkspaceFile | None:
        link = _link(_file("notes.md"), "owner", snapshot)
        view = await REGISTRY[FILE].project(link, link.target, LinkViewerKind.RECIPIENT)
        assert view is None or isinstance(view, PublicWorkspaceFile)
        return view

    async def test_a_link_with_no_snapshot_shows_nothing(self, stored):
        assert await self._view(None) is None
        stored.assert_not_awaited()

    async def test_text_ships_from_the_snapshot_store(self, stored, no_origin):
        view = await self._view(_snapshot())

        assert view == PublicWorkspaceFile(
            target_type=FILE,
            filename="notes.md",
            content_type="text/markdown",
            size_bytes=5,
            text="# Hi\N{REPLACEMENT CHARACTER}",
        )
        stored.assert_awaited_once_with("owner", "a" * 26)

    async def test_html_is_framed_from_the_content_origin_not_shipped_as_text(self, stored, origin):
        view = await self._view(_snapshot(mime="text/html", render=RenderMode.FRAME_ACTIVE))

        assert view is not None
        assert view.text is None
        stored.assert_not_awaited()

    async def test_without_a_content_origin_html_ships_as_its_source(self, stored, no_origin):
        view = await self._view(_snapshot(mime="text/html", render=RenderMode.FRAME_ACTIVE))

        assert view is not None
        assert view.text == "# Hi\N{REPLACEMENT CHARACTER}"

    async def test_bytes_the_link_may_not_serve_ship_no_text(self, stored, no_origin):
        view = await self._view(_snapshot(content_id=None))

        assert view is not None
        assert view.text is None
        stored.assert_not_awaited()

    async def test_text_over_the_view_cap_is_a_metadata_card(self, stored, no_origin):
        view = await self._view(_snapshot(size_bytes=MAX_VIEW_TEXT_BYTES + 1))

        assert view is not None
        assert view.text is None

    async def test_text_at_the_view_cap_still_ships(self, stored, no_origin):
        view = await self._view(_snapshot(size_bytes=MAX_VIEW_TEXT_BYTES))

        assert view is not None
        assert view.text is not None

    async def test_a_binary_file_is_a_metadata_card_never_its_bytes(self, stored, no_origin):
        view = await self._view(_snapshot(mime="application/pdf", render=RenderMode.PDF))

        assert view is not None
        assert view.text is None
        stored.assert_not_awaited()


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
            patch(
                "app.services.links.targets.openui_artifact.openui_artifact_repository"
            ) as artifacts,
            patch("app.services.links.targets.openui_artifact.user_repository") as users,
        ):
            artifacts.get = AsyncMock(return_value=artifact)
            users.get = AsyncMock(return_value=owner)
            view = await _project(ShortLinkTargetType.OPENUI_ARTIFACT, "owner", "a1")

        assert isinstance(view, PublicOpenUIArtifact)
        assert (view.shared_by, view.program) == ("Maya Chen", artifact.program)
        body = view.model_dump_json()
        for leaked in ("maya@example.com", "conv-secret", "brief-secret", "owner"):
            assert leaked not in body
        artifacts.get.assert_awaited_once_with("a1", user_id="owner")

    @pytest.mark.parametrize("owner_name", [None, ""])
    async def test_an_owner_without_a_name_shares_anonymously(self, owner_name):
        artifact = OpenUIArtifact(
            id="a1",
            user_id="owner",
            kind=ArtifactKind.REPORT,
            title="Pilot",
            program='root = Artifact("Pilot", "s", [], [])',
            brief_hash="h",
            model="gpt-6-luna",
        )
        owner = AsyncMock()
        owner.name = owner_name
        with (
            patch(
                "app.services.links.targets.openui_artifact.openui_artifact_repository"
            ) as artifacts,
            patch("app.services.links.targets.openui_artifact.user_repository") as users,
        ):
            artifacts.get = AsyncMock(return_value=artifact)
            users.get = AsyncMock(return_value=owner)
            view = await _project(ShortLinkTargetType.OPENUI_ARTIFACT, "owner", "a1")

        assert view is not None and view.shared_by is None
        users.get.assert_awaited_once_with("owner")

    async def test_a_vanished_owner_shares_anonymously(self):
        artifact = OpenUIArtifact(
            id="a1",
            user_id="owner",
            kind=ArtifactKind.REPORT,
            title="Pilot",
            program='root = Artifact("Pilot", "s", [], [])',
            brief_hash="h",
            model="gpt-6-luna",
        )
        with (
            patch(
                "app.services.links.targets.openui_artifact.openui_artifact_repository"
            ) as artifacts,
            patch("app.services.links.targets.openui_artifact.user_repository") as users,
        ):
            artifacts.get = AsyncMock(return_value=artifact)
            users.get = AsyncMock(return_value=None)
            view = await _project(ShortLinkTargetType.OPENUI_ARTIFACT, "owner", "a1")

        assert view is not None and view.shared_by is None

    async def test_someone_elses_artifact_projects_to_nothing(self):
        with patch(
            "app.services.links.targets.openui_artifact.openui_artifact_repository"
        ) as artifacts:
            artifacts.get = AsyncMock(return_value=None)
            assert await _project(ShortLinkTargetType.OPENUI_ARTIFACT, "x", "a1") is None


async def test_an_artifacts_export_is_its_pdf_named_by_title_and_logged() -> None:
    artifact = OpenUIArtifact(
        id="a1",
        user_id="owner",
        kind=ArtifactKind.REPORT,
        title="Q3 plan",
        program="p",
        brief_hash="h",
        model="gpt-6-luna",
    )
    spec = REGISTRY[ShortLinkTargetType.OPENUI_ARTIFACT]
    assert spec.export is not None
    with patch(
        "app.services.links.targets.openui_artifact.owner_artifact_pdf",
        AsyncMock(return_value=(artifact, b"%PDF-1.7")),
    ) as printed:
        async with captured_wide_event() as event:
            exported = await spec.export(
                "owner", RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="a1")
            )

    printed.assert_awaited_once_with("owner", "a1")
    assert (exported.body, exported.media_type) == (b"%PDF-1.7", "application/pdf")
    assert exported.headers["Content-Disposition"] == 'attachment; filename="Q3 plan.pdf"'
    assert event["artifact"] == {"kind": "report", "pdf_bytes": 8}
