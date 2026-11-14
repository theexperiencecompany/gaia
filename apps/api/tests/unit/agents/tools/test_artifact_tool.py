"""create_artifact: the real tool streams batched deltas, then one done frame, and reports in prose."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools import artifact_tool
from app.agents.tools.artifact_tool import _DeltaBatcher
from app.constants.openui_artifacts import (
    ARTIFACT_DELTA_EVENT,
    ARTIFACT_DELTA_FLUSH_CHARS,
    ARTIFACT_DELTA_FLUSH_SECONDS,
    ARTIFACT_DONE_EVENT,
)
from app.models.openui_artifact_models import ArtifactFailureReason, ArtifactKind
from app.models.short_link_models import ShortLinkTargetType
from app.services.openui_artifacts.create import ArtifactCreationError
from app.services.openui_artifacts.generate import ArtifactRequest

_TOOL = "app.agents.tools.artifact_tool"
CONFIG = RunnableConfig(
    metadata={"user_id": "user-1"}, configurable={"user_id": "user-1", "vfs_session_id": "conv-1"}
)
ARGS: dict[str, Any] = {"kind": "report", "title": "Q3 plan", "brief": "revenue is up 12%"}

INTERACTIVE_ARGS: dict[str, Any] = {**ARGS, "interactive": True}


class TestDeltaBatcher:
    def _batcher(self) -> tuple[_DeltaBatcher, MagicMock]:
        writer = MagicMock()
        return _DeltaBatcher(writer, "s1", ArtifactKind.REPORT, "Q3 plan"), writer

    async def test_small_deltas_wait_and_leave_as_one_frame_carrying_the_header(self) -> None:
        batcher, writer = self._batcher()

        await batcher.push("root = ")
        await batcher.push("Artifact(")
        writer.assert_not_called()
        batcher.flush()

        writer.assert_called_once_with(
            {
                ARTIFACT_DELTA_EVENT: {
                    "stream_id": "s1",
                    "kind": "report",
                    "title": "Q3 plan",
                    "delta": "root = Artifact(",
                }
            }
        )

    async def test_a_large_delta_flushes_at_once(self) -> None:
        batcher, writer = self._batcher()

        await batcher.push("x" * ARTIFACT_DELTA_FLUSH_CHARS)

        writer.assert_called_once()

    async def test_a_slow_delta_flushes_even_when_small(self) -> None:
        writer = MagicMock()
        with patch(f"{_TOOL}.time.monotonic", side_effect=[100.0, 101.0, 101.0]):
            batcher = _DeltaBatcher(writer, "s1", ArtifactKind.REPORT, "Q3 plan")
            await batcher.push("a")

        writer.assert_called_once()

    async def test_the_wait_is_over_exactly_at_the_flush_interval(self) -> None:
        writer = MagicMock()
        with patch(f"{_TOOL}.time.monotonic", side_effect=[0.0, ARTIFACT_DELTA_FLUSH_SECONDS, 0.0]):
            batcher = _DeltaBatcher(writer, "s1", ArtifactKind.REPORT, "Q3 plan")
            await batcher.push("a")

        writer.assert_called_once()

    async def test_deltas_add_up_to_the_size_that_flushes(self) -> None:
        batcher, writer = self._batcher()

        await batcher.push("x" * (ARTIFACT_DELTA_FLUSH_CHARS - 1))
        writer.assert_not_called()
        await batcher.push("x")

        writer.assert_called_once()

    async def test_a_flush_starts_the_size_count_over(self) -> None:
        batcher, writer = self._batcher()
        await batcher.push("x" * ARTIFACT_DELTA_FLUSH_CHARS)
        writer.reset_mock()

        await batcher.push("x" * (ARTIFACT_DELTA_FLUSH_CHARS - 1))

        writer.assert_not_called()

    async def test_a_quick_small_delta_waits(self) -> None:
        writer = MagicMock()
        with patch(f"{_TOOL}.time.monotonic", side_effect=[100.0, 100.01]):
            batcher = _DeltaBatcher(writer, "s1", ArtifactKind.REPORT, "Q3 plan")
            await batcher.push("a")

        writer.assert_not_called()

    async def test_flushing_twice_sends_nothing_new(self) -> None:
        batcher, writer = self._batcher()
        await batcher.push("a")
        batcher.flush()
        batcher.flush()

        assert writer.call_count == 1

    async def test_after_a_flush_the_next_frame_carries_only_the_new_text(self) -> None:
        batcher, writer = self._batcher()
        await batcher.push("a" * ARTIFACT_DELTA_FLUSH_CHARS)
        await batcher.push("b")
        batcher.flush()

        assert [
            call.args[0][ARTIFACT_DELTA_EVENT]["delta"][:1] for call in writer.call_args_list
        ] == [
            "a",
            "b",
        ]
        assert writer.call_args_list[1].args[0][ARTIFACT_DELTA_EVENT]["delta"] == "b"


@pytest.fixture
def writer() -> Iterator[MagicMock]:
    stream = MagicMock()
    with patch(f"{_TOOL}.current_stream_writer", return_value=stream):
        yield stream


@pytest.mark.usefixtures("fake_redis")
class TestCreateArtifact:
    async def test_a_made_artifact_is_announced_ready_and_the_agent_told_where_to_find_it(
        self, writer: MagicMock
    ) -> None:
        artifact = MagicMock(id="a1")
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=artifact)) as create,
            patch(
                f"{_TOOL}.optional_short_link", AsyncMock(return_value="https://heygaia.link/abc")
            ) as link,
        ):
            result = await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        request: ArtifactRequest = create.await_args.args[0]
        assert request == ArtifactRequest(
            kind=ArtifactKind.REPORT,
            brief="revenue is up 12%",
            user_id="user-1",
            conversation_id="conv-1",
            interactive=False,
        )
        assert create.await_args.args[1] == "Q3 plan"
        link.assert_awaited_once_with("user-1", ShortLinkTargetType.OPENUI_ARTIFACT, "a1")
        [done] = [c.args[0] for c in writer.call_args_list if ARTIFACT_DONE_EVENT in c.args[0]]
        card = done[ARTIFACT_DONE_EVENT]
        assert (card["kind"], card["title"], card["status"], card["artifact_id"]) == (
            "report",
            "Q3 plan",
            "ready",
            "a1",
        )
        assert card["stream_id"]
        assert result == (
            'Created the report "Q3 plan". The user sees it as a card in chat and can open it '
            "there; do not repeat its contents in your reply. Public link: https://heygaia.link/abc."
        )

    async def test_an_artifact_without_a_link_says_nothing_of_one(self, writer: MagicMock) -> None:
        with (
            patch(f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))),
            patch(f"{_TOOL}.optional_short_link", AsyncMock(return_value=None)),
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
            patch(f"{_TOOL}.optional_short_link", AsyncMock(return_value=None)),
        ):
            await artifact_tool.create_artifact.ainvoke(INTERACTIVE_ARGS, config=CONFIG)

        assert create.await_args.args[0].interactive is True

    async def test_artifacts_are_not_interactive_unless_asked(self, writer: MagicMock) -> None:
        with (
            patch(
                f"{_TOOL}.create_openui_artifact", AsyncMock(return_value=MagicMock(id="a1"))
            ) as create,
            patch(f"{_TOOL}.optional_short_link", AsyncMock(return_value=None)),
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
            patch(f"{_TOOL}.optional_short_link", AsyncMock()) as link,
        ):
            result = await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        [done] = [c.args[0] for c in writer.call_args_list if ARTIFACT_DONE_EVENT in c.args[0]]
        assert done[ARTIFACT_DONE_EVENT]["status"] == "failed"
        assert "artifact_id" not in done[ARTIFACT_DONE_EVENT]
        link.assert_not_awaited()
        lines = result.splitlines()
        assert lines[0] == "The report could not be made (validation)."
        assert lines[1:] == [f"- problem {i}" for i in range(10)]

    async def test_an_unexpected_failure_closes_the_card_and_still_surfaces(
        self, writer: MagicMock
    ) -> None:
        async def broken(request: ArtifactRequest, title: str, sink) -> None:
            await sink("root = Art")
            raise ConnectionError("provider down")

        with (
            patch(f"{_TOOL}.create_openui_artifact", broken),
            patch(f"{_TOOL}.optional_short_link", AsyncMock()) as link,
            pytest.raises(ConnectionError, match="provider down"),
        ):
            await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        delta, done = (c.args[0] for c in writer.call_args_list)
        assert delta[ARTIFACT_DELTA_EVENT]["delta"] == "root = Art"
        assert done[ARTIFACT_DONE_EVENT]["status"] == "failed"
        assert "artifact_id" not in done[ARTIFACT_DONE_EVENT]
        link.assert_not_awaited()

    async def test_deltas_are_flushed_before_the_outcome_frame(self, writer: MagicMock) -> None:
        async def streaming(request: ArtifactRequest, title: str, sink) -> MagicMock:
            await sink("root = Artifact()")
            return MagicMock(id="a1")

        with (
            patch(f"{_TOOL}.create_openui_artifact", streaming),
            patch(f"{_TOOL}.optional_short_link", AsyncMock(return_value=None)),
        ):
            await artifact_tool.create_artifact.ainvoke(ARGS, config=CONFIG)

        delta, done = (c.args[0] for c in writer.call_args_list)
        assert list(delta) == [ARTIFACT_DELTA_EVENT]
        assert list(done) == [ARTIFACT_DONE_EVENT]
        header = {k: v for k, v in delta[ARTIFACT_DELTA_EVENT].items() if k != "delta"}
        assert header == {
            k: v
            for k, v in done[ARTIFACT_DONE_EVENT].items()
            if k in ("stream_id", "kind", "title")
        }
        assert (header["kind"], header["title"]) == ("report", "Q3 plan")
