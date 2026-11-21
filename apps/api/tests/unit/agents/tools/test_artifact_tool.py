"""create_artifact: the real tool writes one artifact_done card per run and reports in prose."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
import pytest
import time_machine

from app.agents.tools import artifact_tool
from app.constants.openui_artifacts import ARTIFACT_DONE_EVENT
from app.models.openui_artifact_models import ArtifactFailureReason, ArtifactKind
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.services.links.placeholders import LINK_NOTE, link_placeholder
from app.services.openui_artifacts.create import ArtifactCreationError
from app.services.openui_artifacts.generate import ArtifactRequest

_TOOL = "app.agents.tools.artifact_tool"
CONFIG = RunnableConfig(
    metadata={"user_id": "user-1"},
    configurable={"user_id": "user-1", "vfs_session_id": "conv-1", "user_timezone": "+05:30"},
)
ARGS: dict[str, Any] = {"kind": "report", "title": "Q3 plan", "brief": "revenue is up 12%"}

INTERACTIVE_ARGS: dict[str, Any] = {**ARGS, "interactive": True}


@pytest.fixture
def writer() -> Iterator[MagicMock]:
    stream = MagicMock()
    with patch(f"{_TOOL}.current_stream_writer", return_value=stream):
        yield stream


@pytest.mark.usefixtures("fake_redis")
class TestCreateArtifact:
    # 20:00 UTC on 3 November is already 4 November on the user's +05:30 clock.
    @time_machine.travel(datetime(2026, 11, 3, 20, 0, tzinfo=UTC), tick=False)
    async def test_a_made_artifact_is_announced_ready_and_the_agent_told_where_to_find_it(
        self, writer: MagicMock
    ) -> None:
        artifact = MagicMock(id="a1")
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=artifact)) as create,
            patch(
                f"{_TOOL}.attach_link",
                AsyncMock(
                    return_value=ShortLink(
                        slug="abcdefghijk",
                        user_id="user-1",
                        target=RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="a1"),
                    )
                ),
            ) as link,
        ):
            result = await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        request: ArtifactRequest = create.await_args.args[0]
        assert request == ArtifactRequest(
            kind=ArtifactKind.REPORT,
            brief="revenue is up 12%",
            user_id="user-1",
            conversation_id="conv-1",
            today=date(2026, 11, 4),
            interactive=False,
        )
        assert create.await_args.args[1] == "Q3 plan"
        link.assert_awaited_once_with(
            "user-1", RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="a1")
        )
        [done] = [c.args[0] for c in writer.call_args_list if ARTIFACT_DONE_EVENT in c.args[0]]
        card = done[ARTIFACT_DONE_EVENT]
        assert (card["kind"], card["title"], card["status"], card["artifact_id"]) == (
            "report",
            "Q3 plan",
            "ready",
            "a1",
        )
        assert card["stream_id"]
        placeholder = link_placeholder(
            RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="a1")
        )
        assert result == (
            'Created the report "Q3 plan". The user sees it as a card in chat and can open it '
            f"there; do not repeat its contents in your reply. {LINK_NOTE} Its link: {placeholder}"
        )
        assert "abcdefghijk" not in result

    async def test_an_artifact_without_a_link_says_nothing_of_one(self, writer: MagicMock) -> None:
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))),
            patch(f"{_TOOL}.attach_link", AsyncMock(return_value=None)),
        ):
            result = await artifact_tool.create_artifact.ainvoke(INTERACTIVE_ARGS, config=CONFIG)

        assert result == (
            'Created the report "Q3 plan". The user sees it as a card in chat and can open it '
            "there; do not repeat its contents in your reply."
        )

    async def test_the_interactive_flag_reaches_the_request(self, writer: MagicMock) -> None:
        with (
            patch(
                f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))
            ) as create,
            patch(f"{_TOOL}.attach_link", AsyncMock(return_value=None)),
        ):
            await artifact_tool.create_artifact.ainvoke(INTERACTIVE_ARGS, config=CONFIG)

        assert create.await_args.args[0].interactive is True

    async def test_artifacts_are_not_interactive_unless_asked(self, writer: MagicMock) -> None:
        with (
            patch(
                f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))
            ) as create,
            patch(f"{_TOOL}.attach_link", AsyncMock(return_value=None)),
        ):
            tool = artifact_tool.create_artifact
            assert isinstance(tool, StructuredTool) and tool.coroutine is not None
            await tool.coroutine(
                config=CONFIG, kind=ArtifactKind.REPORT, title="Q3 plan", brief="revenue is up 12%"
            )

        assert create.await_args.args[0].interactive is False

    async def test_a_failed_artifact_is_announced_failed_and_its_problems_listed(
        self, writer: MagicMock
    ) -> None:
        failure = ArtifactCreationError(
            message="gave up",
            reason=ArtifactFailureReason.VALIDATION,
            problems=[f"problem {i}" for i in range(12)],
        )
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(side_effect=failure)),
            patch(f"{_TOOL}.attach_link", AsyncMock()) as link,
        ):
            result = await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        [done] = [c.args[0] for c in writer.call_args_list if ARTIFACT_DONE_EVENT in c.args[0]]
        assert done[ARTIFACT_DONE_EVENT]["status"] == "failed"
        assert done[ARTIFACT_DONE_EVENT]["reason"] == "validation"
        assert "artifact_id" not in done[ARTIFACT_DONE_EVENT]
        link.assert_not_awaited()
        lines = result.splitlines()
        assert lines[0] == "The report could not be made (validation)."
        assert lines[1:] == [f"- problem {i}" for i in range(10)]

    async def test_an_unexpected_failure_closes_the_card_and_still_surfaces(
        self, writer: MagicMock
    ) -> None:
        with (
            patch(
                f"{_TOOL}.create_openui_artifact",
                AsyncMock(side_effect=ConnectionError("provider down")),
            ),
            patch(f"{_TOOL}.attach_link", AsyncMock()) as link,
            pytest.raises(ConnectionError, match="provider down"),
        ):
            await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        [done] = (c.args[0] for c in writer.call_args_list)
        assert done[ARTIFACT_DONE_EVENT]["status"] == "failed"
        assert "artifact_id" not in done[ARTIFACT_DONE_EVENT]
        link.assert_not_awaited()

    async def test_a_run_writes_only_its_done_card(self, writer: MagicMock) -> None:
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))),
            patch(f"{_TOOL}.attach_link", AsyncMock(return_value=None)),
        ):
            await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        [done] = (c.args[0] for c in writer.call_args_list)
        assert list(done) == [ARTIFACT_DONE_EVENT]
        assert (done[ARTIFACT_DONE_EVENT]["kind"], done[ARTIFACT_DONE_EVENT]["title"]) == (
            "report",
            "Q3 plan",
        )
