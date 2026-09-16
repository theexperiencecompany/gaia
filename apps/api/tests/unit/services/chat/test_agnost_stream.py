"""Turn telemetry on the streaming chat path.

Every surface (web, desktop, mobile, bots, voice) funnels through
``run_chat_stream_background``, so the fan-out opened there must carry the
real user id, conversation id, and input, and close with the real output and
one coherent outcome — and a telemetry failure must never break the turn.
"""

import asyncio
from collections.abc import AsyncGenerator, Iterator
import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import HIL_ACK_APPROVED, HIL_ACK_DENIED
from app.models.message_models import FileData, MessageRequestWithHistory
from app.services.analytics_service import AnalyticsEvents
from app.services.chat.stream import (
    _resolve_pending_approval_turn,
    _StreamState,
    run_chat_stream_background,
)


@pytest.fixture
def test_user() -> dict:
    return {"user_id": "user_abc", "email": "tester@example.com"}


@pytest.fixture
def existing_conv_body() -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message="Follow-up",
        messages=[{"role": "user", "content": "Follow-up"}],
        conversation_id="conv_existing_123",
    )


async def _done_only_stream() -> AsyncGenerator[str, None]:
    yield "data: [DONE]\n\n"


async def _text_then_nostream(text: str, complete: str) -> AsyncGenerator[str, None]:
    yield f"data: {json.dumps({'response': text})}\n\n"
    yield f"nostream: {json.dumps({'complete_message': complete})}"
    yield "data: [DONE]\n\n"


async def _error_frame_then_nostream() -> AsyncGenerator[str, None]:
    yield f"data: {json.dumps({'error': 'graph exploded'})}\n\n"
    yield f"nostream: {json.dumps({'complete_message': 'partial'})}"
    yield "data: [DONE]\n\n"


async def _cancelled_stream() -> AsyncGenerator[str, None]:
    if False:  # pragma: no cover
        yield ""
    raise asyncio.CancelledError("deploy restart")


def _make_stream_manager_mock(is_cancelled: bool = False) -> MagicMock:
    m = MagicMock()
    m.publish_chunk = AsyncMock()
    m.is_cancelled = AsyncMock(return_value=is_cancelled)
    m.update_progress = AsyncMock()
    m.complete_stream = AsyncMock()
    m.set_error = AsyncMock()
    m.cleanup = AsyncMock()
    m.get_progress = AsyncMock(return_value=None)
    return m


@contextlib.contextmanager
def _patch_stream_manager(sm: MagicMock) -> Iterator[MagicMock]:
    with contextlib.ExitStack() as stack:
        for path in (
            "app.services.chat.stream.stream_manager",
            "app.services.chat.chunks.stream_manager",
            "app.services.chat.state.stream_manager",
            "app.services.chat.artifact_forwarder.stream_manager",
            "app.utils.stream_publishers.stream_manager",
        ):
            stack.enter_context(patch(path, sm))
        yield sm


def _usage_callback_class() -> MagicMock:
    return MagicMock(return_value=MagicMock(usage_metadata={}))


@pytest.fixture(autouse=True)
def _quiet_turn() -> Iterator[None]:
    """Stub the turn's side channels so tests exercise telemetry only."""
    with (
        patch(
            "app.services.chat.stream.resolve_pending_from_message",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.chat.artifact_forwarder.redis_cache.redis", None),
        # PostHog capture is a separate seam with its own tests; the provider
        # registry is ambient process state, so a real call here would couple
        # these tests to whatever registered "posthog" first (or raise when
        # nothing did). The telemetry assertions below are what this file owns.
        patch("app.services.chat.stream.capture_event", new=MagicMock()),
    ):
        yield


async def _run_turn(
    sm: MagicMock,
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    agent_stream: AsyncGenerator[str, None],
    source: str | None = None,
) -> None:
    with (
        _patch_stream_manager(sm),
        patch(
            "app.services.chat.stream.call_agent",
            new=AsyncMock(return_value=agent_stream),
        ),
        patch(
            "app.services.chat.stream.save_conversation_async",
            new=AsyncMock(),
        ),
        patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
    ):
        await run_chat_stream_background(
            stream_id="stream_agnost",
            body=body,
            user=user,
            conversation_id=conversation_id,
            source=source,
        )


@pytest.mark.unit
class TestTurnTelemetry:
    async def test_success_opens_and_closes_with_real_ids_and_text(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat.stream.begin_turn_all") as mock_begin_all,
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
        ):
            await _run_turn(
                sm,
                existing_conv_body,
                test_user,
                "conv_existing_123",
                _text_then_nostream("Follow", "Follow-up complete"),
            )

        mock_begin_all.assert_called_once()
        spec = mock_begin_all.call_args.args[0]
        assert spec.user_id == "user_abc"
        assert spec.conversation_id == "conv_existing_123"
        assert spec.user_input == "Follow-up"
        assert spec.source is None
        assert spec.mode == "interactive"
        assert spec.properties == {
            "voice_mode": False,
            "is_new_conversation": False,
            "selected_tool": None,
        }

        mock_agnost_end.assert_called_once()
        end_kwargs = mock_agnost_end.call_args.kwargs
        assert end_kwargs["output"] == "Follow-up complete"
        assert end_kwargs["success"] is True
        assert end_kwargs["properties"]["cancelled"] is False
        # One outcome everywhere: no error reaches any vendor on success.
        assert mock_lat_end.call_args.kwargs["error"] is None
        assert mock_lam_end.call_args.kwargs["error"] is None

    async def test_agent_error_closes_with_error(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()

        async def _failing_stream() -> AsyncGenerator[str, None]:
            if False:  # pragma: no cover
                yield ""
            raise RuntimeError("provider down")

        with (
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
        ):
            await _run_turn(
                sm, existing_conv_body, test_user, "conv_existing_123", _failing_stream()
            )

        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["output"], "the failure must carry a message"
        lat_error = mock_lat_end.call_args.kwargs["error"]
        assert isinstance(lat_error, RuntimeError) and str(lat_error) == "provider down"
        assert mock_lam_end.call_args.kwargs["error"] is lat_error

    async def test_cancelled_turn_marks_cancelled(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock(is_cancelled=True)
        with (
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
        ):
            await _run_turn(
                sm,
                existing_conv_body,
                test_user,
                "conv_existing_123",
                _text_then_nostream("partial", "partial"),
            )

        mock_agnost_end.assert_called_once()
        assert mock_agnost_end.call_args.kwargs["output"] == "partial"
        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["properties"]["cancelled"] is True
        assert mock_agnost_end.call_args.kwargs["properties"]["outcome"] == "cancelled"
        # Cancelled is not a failure: no error reaches any trace backend.
        assert mock_lat_end.call_args.kwargs["error"] is None
        assert mock_lat_end.call_args.kwargs["cancelled"] is True
        assert mock_lam_end.call_args.kwargs["output"] == "partial"
        assert mock_lam_end.call_args.kwargs["error"] is None
        assert mock_lam_end.call_args.kwargs["cancelled"] is True

    async def test_empty_user_id_opens_turn_unattributed(self, existing_conv_body):
        """The `or ""` guard pins the anonymous shape: no user must never
        break the turn or misattribute it."""
        sm = _make_stream_manager_mock()
        with patch("app.services.chat.stream.begin_turn_all") as mock_begin_all:
            await _run_turn(
                sm,
                existing_conv_body,
                {"user_id": ""},
                "conv_existing_123",
                _text_then_nostream("Follow", "Follow-up complete"),
            )

        assert mock_begin_all.call_args.args[0].user_id == ""

    async def test_telemetry_explosion_never_breaks_the_turn(self, test_user, existing_conv_body):
        """Sabotage below the services: the real fan-out must still not break the turn."""
        sm = _make_stream_manager_mock()
        settings = SimpleNamespace(AGNOST_ORG_ID="org-1", AGNOST_ENDPOINT="https://api.agnost.ai")
        with (
            patch("app.services.agnost_service.settings", settings),
            patch(
                "app.services.agnost_service.agnost.begin",
                side_effect=RuntimeError("telemetry down"),
            ),
        ):
            await _run_turn(
                sm,
                existing_conv_body,
                test_user,
                "conv_existing_123",
                _text_then_nostream("Follow", "Follow-up complete"),
            )

        published = [call.args[1] for call in sm.publish_chunk.call_args_list]
        assert "data: [DONE]\n\n" in published

    async def test_description_task_receives_identity(self, test_user):
        """The detached title task gets the conversation, user, and bot
        message id — without them its spans orphan and its spend unattributed."""
        sm = _make_stream_manager_mock()
        new_body = MessageRequestWithHistory(
            message="Hello GAIA",
            messages=[{"role": "user", "content": "Hello GAIA"}],
            conversation_id=None,
        )
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch(
                "app.services.chat.stream.initialize_new_conversation",
                new=AsyncMock(return_value="data: init\n\n"),
            ),
            patch(
                "app.services.chat.stream.generate_and_update_description",
                new=AsyncMock(return_value="Hello GAIA"),
            ) as mock_generate,
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_desc",
                body=new_body,
                user=test_user,
                conversation_id="new_conv_id",
            )

        mock_generate.assert_awaited_once()
        args = mock_generate.call_args.args
        assert args[0] == "new_conv_id"
        assert args[2] == test_user
        assert isinstance(args[5], str) and args[5]

    async def test_init_failure_still_surfaces_original_error(self, test_user):
        """If init raises before telemetry opens, the turn must report the init
        failure — not an UnboundLocalError from the telemetry close path."""
        sm = _make_stream_manager_mock()
        new_body = MessageRequestWithHistory(
            message="Hello GAIA",
            messages=[{"role": "user", "content": "Hello GAIA"}],
            conversation_id=None,
        )
        with (
            patch(
                "app.services.chat.stream.initialize_new_conversation",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch("app.services.chat.stream.end_turn_all") as mock_end_all,
        ):
            await _run_turn(sm, new_body, test_user, "new_conv_id", _done_only_stream())

        # Closed with nothing to close — and exactly once, on the error path.
        mock_end_all.assert_called_once()
        assert mock_end_all.call_args.args[0] is None
        published = [call.args[1] for call in sm.publish_chunk.call_args_list]
        assert any('"error"' in chunk and "mongo down" in chunk for chunk in published)

    async def test_hard_cancel_closes_as_cancelled_and_propagates(
        self, test_user, existing_conv_body
    ):
        """CancelledError is BaseException, not Exception: the turn must still
        close its scopes (as cancelled) instead of leaking them."""
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
            pytest.raises(asyncio.CancelledError),
        ):
            await _run_turn(
                sm, existing_conv_body, test_user, "conv_existing_123", _cancelled_stream()
            )

        mock_agnost_end.assert_called_once()
        assert mock_agnost_end.call_args.kwargs["output"] == ""
        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["properties"]["outcome"] == "cancelled"
        assert mock_lat_end.call_args.kwargs["error"] is None
        assert mock_lat_end.call_args.kwargs["cancelled"] is True
        assert mock_lam_end.call_args.kwargs["cancelled"] is True

    async def test_source_reaches_telemetry(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with patch("app.services.chat.stream.begin_turn_all") as mock_begin_all:
            await _run_turn(
                sm,
                existing_conv_body,
                test_user,
                "conv_existing_123",
                _text_then_nostream("Follow", "Follow-up complete"),
                source="desktop",
            )

        assert mock_begin_all.call_args.args[0].source == "desktop"

    async def test_error_frame_marks_posthog_completed_with_error(
        self, test_user, existing_conv_body
    ):
        """A yielded error frame completes the turn without raising, so the
        vendors read failed — PostHog must carry has_error or it reads 100%
        completed during a setup outage."""
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat.stream.capture_event") as mock_capture,
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
        ):
            await _run_turn(
                sm, existing_conv_body, test_user, "conv_existing_123", _error_frame_then_nostream()
            )

        completed = [
            call
            for call in mock_capture.call_args_list
            if call.args[1] == AnalyticsEvents.CHAT_MESSAGE_COMPLETED
        ]
        assert len(completed) == 1
        assert completed[0].args[2]["has_error"] is True
        # ...and the vendors read the same failure, with the message.
        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["output"], "the failure must carry a message"
        lat_error = mock_lat_end.call_args.kwargs["error"]
        assert isinstance(lat_error, Exception) and "graph exploded" in str(lat_error)
        assert mock_lam_end.call_args.kwargs["error"] is lat_error

    async def test_clean_turn_marks_posthog_completed_without_error(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        with patch("app.services.chat.stream.capture_event") as mock_capture:
            await _run_turn(
                sm,
                existing_conv_body,
                test_user,
                "conv_existing_123",
                _text_then_nostream("Follow", "Follow-up complete"),
            )

        completed = [
            call
            for call in mock_capture.call_args_list
            if call.args[1] == AnalyticsEvents.CHAT_MESSAGE_COMPLETED
        ]
        assert len(completed) == 1
        assert completed[0].args[2]["has_error"] is False
        assert completed[0].kwargs["dedupe_key"] == "stream_agnost"

    async def test_new_conversation_uploads_are_seeded(self, test_user):
        sm = _make_stream_manager_mock()
        files = [
            FileData(fileId="f1", url="https://x/y", filename="a.pdf"),
        ]
        new_body = MessageRequestWithHistory(
            message="see attached",
            messages=[{"role": "user", "content": "see attached"}],
            conversation_id=None,
            fileData=files,
        )
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch(
                "app.services.chat.stream.initialize_new_conversation",
                new=AsyncMock(return_value="data: init\n\n"),
            ),
            patch(
                "app.services.chat.stream._wait_for_artifact_forwarder", new=AsyncMock()
            ) as mock_wait,
            patch("app.services.chat.stream.FileService") as mock_files,
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            mock_files.seed_uploads = AsyncMock()
            await run_chat_stream_background(
                stream_id="stream_seed",
                body=new_body,
                user=test_user,
                conversation_id="new_conv_files",
            )

        waiter_args = mock_wait.call_args.args
        assert isinstance(waiter_args[0], asyncio.Event)
        assert waiter_args[1] == "stream_seed"
        mock_files.seed_uploads.assert_awaited_once_with(files, "user_abc", "new_conv_files")

    async def test_anonymous_uploads_are_not_seeded(self):
        """No user, no seed — even with files on a new conversation."""
        sm = _make_stream_manager_mock()
        files = [
            FileData(fileId="f1", url="https://x/y", filename="a.pdf"),
        ]
        new_body = MessageRequestWithHistory(
            message="see attached",
            messages=[{"role": "user", "content": "see attached"}],
            conversation_id=None,
            fileData=files,
        )
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch(
                "app.services.chat.stream.initialize_new_conversation",
                new=AsyncMock(return_value="data: init\n\n"),
            ),
            patch(
                "app.services.chat.stream._wait_for_artifact_forwarder", new=AsyncMock()
            ) as mock_wait,
            patch("app.services.chat.stream.FileService") as mock_files,
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            mock_files.seed_uploads = AsyncMock()
            await run_chat_stream_background(
                stream_id="stream_anon",
                body=new_body,
                user={"user_id": ""},
                conversation_id="new_conv_anon",
            )

        mock_wait.assert_not_awaited()
        mock_files.seed_uploads.assert_not_awaited()

    async def test_existing_conversation_seeds_nothing(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        existing_conv_body.fileData = [
            FileData(fileId="f1", url="https://x/y", filename="a.pdf"),
        ]
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream._wait_for_artifact_forwarder", new=AsyncMock()) as mock_wait,
            patch("app.services.chat.stream.FileService") as mock_files,
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            mock_files.seed_uploads = AsyncMock()
            await run_chat_stream_background(
                stream_id="stream_noseed",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_wait.assert_not_awaited()
        mock_files.seed_uploads.assert_not_awaited()


@pytest.mark.unit
class TestApprovalTurnTelemetry:
    """The bot-channel HIL approval fast-path resolves without running the
    agent — but the classifier call is a real LLM turn on the most
    destructive path, so it opens and closes its own telemetry."""

    def _approval_body(self) -> MessageRequestWithHistory:
        return MessageRequestWithHistory(
            message="yes do it",
            messages=[{"role": "user", "content": "yes do it"}],
            conversation_id="conv_hil_1",
        )

    async def _resolve(self, sm: MagicMock, action: object) -> bool:
        state = _StreamState()
        state.bot_message_id = "bot-9"
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.resolve_pending_from_message",
                new=AsyncMock(return_value=action),
            ) as mock_resolve,
            patch("app.services.chat.stream._persist_turn", new=AsyncMock()),
            patch(
                "app.services.chat.stream.trace_id_for_message", return_value="trace-seed"
            ) as mock_seed,
        ):
            result = await _resolve_pending_approval_turn(
                self._approval_body(),
                {"user_id": "user_abc"},
                "conv_hil_1",
                "stream_hil",
                state,
                "telegram",
            )

        mock_seed.assert_called_once_with("bot-9")
        assert mock_resolve.call_args.args == ("conv_hil_1", "user_abc", "yes do it", [])
        assert mock_resolve.call_args.kwargs == {"langfuse_trace_id": "trace-seed"}
        return result

    async def test_approve_opens_and_closes_with_ack(self) -> None:
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat.stream.begin_turn_all") as mock_begin,
            patch("app.services.chat.stream.end_turn_all") as mock_end,
        ):
            assert await self._resolve(sm, "approve") is True

        spec = mock_begin.call_args.args[0]
        assert spec.user_id == "user_abc"
        assert spec.conversation_id == "conv_hil_1"
        assert spec.user_input == "yes do it"
        assert spec.source == "telegram"
        assert spec.mode == "interactive"
        assert spec.properties == {"approval_flow": "hil_classifier"}
        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == HIL_ACK_APPROVED
        assert mock_end.call_args.kwargs.get("error") is None

    async def test_deny_closes_with_deny_ack(self) -> None:
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat.stream.begin_turn_all") as mock_begin,
            patch("app.services.chat.stream.end_turn_all") as mock_end,
        ):
            assert await self._resolve(sm, "deny") is True

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == HIL_ACK_DENIED

    async def test_unrelated_message_closes_quietly(self) -> None:
        sm = _make_stream_manager_mock()
        with (
            patch("app.services.chat.stream.begin_turn_all") as mock_begin,
            patch("app.services.chat.stream.end_turn_all") as mock_end,
        ):
            assert await self._resolve(sm, None) is False

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == ""

    async def test_classifier_failure_records_error(self) -> None:
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.resolve_pending_from_message",
                new=AsyncMock(side_effect=RuntimeError("classifier down")),
            ),
            patch("app.services.chat.stream.begin_turn_all") as mock_begin,
            patch("app.services.chat.stream.end_turn_all") as mock_end,
        ):
            result = await _resolve_pending_approval_turn(
                self._approval_body(),
                {"user_id": "user_abc"},
                "conv_hil_1",
                "stream_hil",
                _StreamState(),
                "telegram",
            )

        assert result is False
        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert isinstance(mock_end.call_args.kwargs["error"], RuntimeError)
        assert mock_end.call_args.kwargs["output"] == "classifier down"

    async def test_non_bot_source_opens_no_turn(self) -> None:
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch("app.services.chat.stream.begin_turn_all") as mock_begin,
        ):
            result = await _resolve_pending_approval_turn(
                self._approval_body(),
                {"user_id": "user_abc"},
                "conv_hil_1",
                "stream_hil",
                _StreamState(),
                None,
            )

        assert result is False
        mock_begin.assert_not_called()
    async def test_description_task_receives_identity(self, test_user):
        """The detached title task gets the conversation, user, and bot
        message id — without them its spans orphan and its spend unattributed."""
        sm = _make_stream_manager_mock()
        new_body = MessageRequestWithHistory(
            message="Hello GAIA",
            messages=[{"role": "user", "content": "Hello GAIA"}],
            conversation_id=None,
        )
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch(
                "app.services.chat.stream.initialize_new_conversation",
                new=AsyncMock(return_value="data: init\n\n"),
            ),
            patch(
                "app.services.chat.stream.generate_and_update_description",
                new=AsyncMock(return_value="Hello GAIA"),
            ) as mock_generate,
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_desc",
                body=new_body,
                user=test_user,
                conversation_id="new_conv_id",
            )

        mock_generate.assert_awaited_once()
        args = mock_generate.call_args.args
        assert args[0] == "new_conv_id"
        assert args[2] == test_user
        assert isinstance(args[5], str) and args[5]
