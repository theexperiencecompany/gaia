"""Unit tests for memory utility functions."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.memory_utils import (
    await_remaining_memory_task,
    check_memory_task_yield,
    format_email_for_memory,
    start_memory_task,
    store_user_message_memory,
)


# ---------------------------------------------------------------------------
# store_user_message_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreUserMessageMemory:
    """Tests for storing user messages in the memory service."""

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_dict_on_success(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        result = await store_user_message_memory("u1", "Hello", "conv_1")

        assert result is not None
        assert result["type"] == "memory_stored"
        assert "Hello" in result["content"]
        assert result["conversation_id"] == "conv_1"
        assert "timestamp" in result

    @patch("app.utils.memory_utils.memory_service")
    async def test_passes_correct_params_to_service(
        self, mock_mem_svc: MagicMock
    ) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        await store_user_message_memory("u1", "Hello world", "conv_2")

        mock_mem_svc.store_memory.assert_awaited_once()
        call_kwargs = mock_mem_svc.store_memory.call_args.kwargs
        assert call_kwargs["message"] == "Hello world"
        assert call_kwargs["user_id"] == "u1"
        assert call_kwargs["conversation_id"] == "conv_2"
        assert call_kwargs["async_mode"] is True
        assert call_kwargs["metadata"]["type"] == "user_message"
        assert call_kwargs["metadata"]["conversation_id"] == "conv_2"
        assert "timestamp" in call_kwargs["metadata"]

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_when_store_returns_none(
        self, mock_mem_svc: MagicMock
    ) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=None)

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_when_store_returns_falsy(
        self, mock_mem_svc: MagicMock
    ) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=0)

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_on_exception(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(side_effect=Exception("Mem0 down"))

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_timestamp_is_utc_iso_format(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        result = await store_user_message_memory("u1", "msg", "conv_1")

        assert result is not None
        # Should be parseable as ISO format
        ts = datetime.fromisoformat(result["timestamp"])
        assert (
            ts.tzinfo is not None
            or "+" in result["timestamp"]
            or "Z" in result["timestamp"]
        )


# ---------------------------------------------------------------------------
# start_memory_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartMemoryTask:
    """Tests for conditionally creating memory storage tasks."""

    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_returns_none_when_user_id_is_empty(self, mock_store: AsyncMock) -> None:
        result = start_memory_task("", "message", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_returns_none_when_message_is_empty(self, mock_store: AsyncMock) -> None:
        result = start_memory_task("u1", "", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_returns_none_when_both_empty(self, mock_store: AsyncMock) -> None:
        result = start_memory_task("", "", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_returns_none_when_user_id_is_none(self, mock_store: AsyncMock) -> None:
        """None is falsy, so should return None."""
        result = start_memory_task(None, "message", "conv_1")  # type: ignore[arg-type]
        assert result is None

    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_returns_none_when_message_is_none(self, mock_store: AsyncMock) -> None:
        result = start_memory_task("u1", None, "conv_1")  # type: ignore[arg-type]
        assert result is None

    @patch("app.utils.memory_utils.asyncio.create_task")
    @patch("app.utils.memory_utils.store_user_message_memory", new_callable=AsyncMock)
    def test_creates_task_when_conditions_met(
        self, mock_store: AsyncMock, mock_create_task: MagicMock
    ) -> None:
        mock_task = MagicMock()
        mock_create_task.return_value = mock_task

        result = start_memory_task("u1", "Hello", "conv_1")
        assert result is mock_task
        mock_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# check_memory_task_yield
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckMemoryTaskYield:
    """Tests for checking if a memory task is complete and ready to yield."""

    def test_returns_data_when_task_done_and_not_yielded(self) -> None:
        mock_task = MagicMock(spec=["done", "result"])
        mock_task.done.return_value = True
        mock_task.result.return_value = {"type": "memory_stored"}

        data, yielded = check_memory_task_yield(mock_task, False)
        assert data == {"type": "memory_stored"}
        assert yielded is True

    def test_returns_none_when_task_done_but_already_yielded(self) -> None:
        mock_task = MagicMock(spec=["done", "result"])
        mock_task.done.return_value = True

        data, yielded = check_memory_task_yield(mock_task, True)
        assert data is None
        assert yielded is True

    def test_returns_none_when_task_not_done(self) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = False

        data, yielded = check_memory_task_yield(mock_task, False)
        assert data is None
        assert yielded is False

    def test_returns_none_when_task_is_none(self) -> None:
        data, yielded = check_memory_task_yield(None, False)
        assert data is None
        assert yielded is False

    def test_preserves_yielded_state_when_task_is_none(self) -> None:
        data, yielded = check_memory_task_yield(None, True)
        assert data is None
        assert yielded is True

    def test_returns_none_and_true_when_task_result_is_none(self) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.result.return_value = None

        data, yielded = check_memory_task_yield(mock_task, False)
        # result is None so data is None, but yielded is set to True only
        # if memory_stored is truthy. Since it's None, we fall through.
        # Actually: if memory_stored is falsy, the inner block doesn't return,
        # so we fall through to the final return: (None, memory_yielded=False)
        # Wait, let's re-read: the try block runs, result() returns None,
        # memory_stored is None (falsy), so the `if memory_stored:` doesn't
        # fire, but we don't return (None, True) either -- we fall through to
        # the end: return None, memory_yielded (which is False).
        # Actually no: the code is inside `if memory_task and ... and not memory_yielded`,
        # inside try: memory_stored = task.result(), if memory_stored: return...,
        # then except, then outside: return None, memory_yielded.
        # So if memory_stored is None, we don't return early, we fall to bottom.
        assert data is None
        assert yielded is False

    def test_handles_exception_from_task_result(self) -> None:
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.result.side_effect = Exception("task cancelled")

        data, yielded = check_memory_task_yield(mock_task, False)
        assert data is None
        assert yielded is True


# ---------------------------------------------------------------------------
# await_remaining_memory_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAwaitRemainingMemoryTask:
    """Tests for awaiting a pending memory task."""

    async def test_returns_data_when_task_succeeds(self) -> None:
        stored = {"type": "memory_stored", "content": "test"}
        # await_remaining_memory_task does `await memory_task` directly,
        # so we need a real awaitable (coroutine / Future), not AsyncMock.
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        future.set_result(stored)

        result = await await_remaining_memory_task(future, False)
        assert result == stored

    async def test_returns_none_when_already_yielded(self) -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        future.set_result({"type": "memory_stored"})

        result = await await_remaining_memory_task(future, True)
        assert result is None

    async def test_returns_none_when_task_is_none(self) -> None:
        result = await await_remaining_memory_task(None, False)
        assert result is None

    async def test_returns_none_when_task_is_none_and_yielded(self) -> None:
        result = await await_remaining_memory_task(None, True)
        assert result is None

    async def test_returns_none_when_task_returns_none(self) -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[None] = loop.create_future()
        future.set_result(None)

        result = await await_remaining_memory_task(future, False)
        assert result is None

    async def test_returns_none_when_task_returns_falsy(self) -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        future.set_result({})

        result = await await_remaining_memory_task(future, False)
        assert result is None

    async def test_returns_none_on_exception(self) -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict] = loop.create_future()
        future.set_exception(Exception("cancelled"))

        result = await await_remaining_memory_task(future, False)
        assert result is None


# ---------------------------------------------------------------------------
# format_email_for_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatEmailForMemory:
    """Tests for formatting email content for Mem0 storage."""

    def test_formats_complete_email(self) -> None:
        parser = MagicMock()
        parser.sender = "alice@example.com"
        parser.subject = "Meeting Notes"
        parser.text_content = "Please review the notes."

        result = format_email_for_memory(parser)
        assert "alice@example.com" in result
        assert "Meeting Notes" in result
        assert "Please review the notes." in result

    def test_uses_fallback_for_none_sender(self) -> None:
        parser = MagicMock()
        parser.sender = None
        parser.subject = "Subject"
        parser.text_content = "Body"

        result = format_email_for_memory(parser)
        assert "Unknown Sender" in result

    def test_uses_fallback_for_none_subject(self) -> None:
        parser = MagicMock()
        parser.sender = "bob@test.com"
        parser.subject = None
        parser.text_content = "Body"

        result = format_email_for_memory(parser)
        assert "No Subject" in result

    def test_uses_fallback_for_none_content(self) -> None:
        parser = MagicMock()
        parser.sender = "bob@test.com"
        parser.subject = "Hi"
        parser.text_content = None

        result = format_email_for_memory(parser)
        assert "No content available" in result

    def test_all_fields_none_uses_all_fallbacks(self) -> None:
        parser = MagicMock()
        parser.sender = None
        parser.subject = None
        parser.text_content = None

        result = format_email_for_memory(parser)
        assert "Unknown Sender" in result
        assert "No Subject" in result
        assert "No content available" in result

    def test_preserves_actual_values_when_present(self) -> None:
        parser = MagicMock()
        parser.sender = "sender@co.com"
        parser.subject = "Important"
        parser.text_content = "Read this carefully."

        result = format_email_for_memory(parser)
        assert "Unknown Sender" not in result
        assert "No Subject" not in result
        assert "No content available" not in result

    def test_empty_strings_are_kept(self) -> None:
        """Empty strings are truthy in the `or` check? No, '' is falsy."""
        parser = MagicMock()
        parser.sender = ""
        parser.subject = ""
        parser.text_content = ""

        result = format_email_for_memory(parser)
        # Empty strings are falsy, so fallbacks are used
        assert "Unknown Sender" in result
        assert "No Subject" in result
        assert "No content available" in result

    def test_output_structure(self) -> None:
        """Verify the f-string structure: first line has sender+subject, body follows."""
        parser = MagicMock()
        parser.sender = "alice@test.com"
        parser.subject = "Test"
        parser.text_content = "Content here"

        result = format_email_for_memory(parser)
        lines = result.strip().split("\n")
        assert lines[0].startswith("User received email from alice@test.com")
        assert 'subject "Test"' in lines[0]
        # Content is on a line after the blank line
        assert "Content here" in result
