"""Unit tests for memory_tasks ARQ worker."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.email import NO_SUBJECT, UNKNOWN_SENDER
from app.constants.memory import MemorySourceType
from app.memory.engine import RetainResult
from app.workers.tasks.memory_tasks import store_memories_batch


def _retain_result(facts_extracted: int = 1) -> RetainResult:
    return RetainResult(facts_extracted=facts_extracted, new=facts_extracted)


@pytest.mark.unit
class TestStoreMemoriesBatch:
    """Tests for store_memories_batch ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    @pytest.fixture
    def single_email(self) -> list[dict]:
        return [
            {
                "content": "Hello, you have been accepted to the Python conference.",
                "metadata": {
                    "subject": "Conference Acceptance",
                    "sender": "no-reply@pycon.org",
                },
            }
        ]

    @pytest.fixture
    def multi_email_batch(self) -> list[dict]:
        return [
            {
                "content": "Your subscription to GitHub Pro has been renewed.",
                "metadata": {
                    "subject": "GitHub Pro Renewal",
                    "sender": "billing@github.com",
                },
            },
            {
                "content": "Welcome to the team! You start Monday at Acme Corp.",
                "metadata": {"subject": "Offer Letter", "sender": "hr@acme.com"},
            },
            {
                "content": "Your flight to San Francisco is confirmed.",
                "metadata": {
                    "subject": "Flight Confirmation",
                    "sender": "noreply@airline.com",
                },
            },
        ]

    async def test_empty_batch_returns_early(self, ctx):
        result = await store_memories_batch(ctx, "user_abc", [])
        assert "No emails to process" in result
        assert "user_abc" in result

    async def test_single_email_stored_successfully(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result(2))

            result = await store_memories_batch(
                ctx,
                "user_abc",
                single_email,
                user_name="Alice Smith",
                user_email="alice@example.com",
            )

        assert "Extracted 2 memories from 1 emails" in result
        mock_engine.retain.assert_called_once()
        # Verify the actual transcript handed to the engine, not just the return string.
        call = mock_engine.retain.call_args
        stored_messages = call.args[1]
        assert len(stored_messages) == 1
        assert stored_messages[0]["role"] == "user"
        assert "Conference Acceptance" in stored_messages[0]["content"]
        assert "no-reply@pycon.org" in stored_messages[0]["content"]
        assert "Python conference" in stored_messages[0]["content"]

    async def test_batch_stored_successfully(self, ctx, multi_email_batch):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result(3))

            result = await store_memories_batch(
                ctx,
                "user_abc",
                multi_email_batch,
                user_name="Alice Smith",
                user_email="alice@example.com",
            )

        assert "Extracted 3 memories from 3 emails" in result
        call = mock_engine.retain.call_args
        stored_messages = call.args[1]
        assert len(stored_messages) == 3, (
            f"Expected 3 email messages in engine call, got {len(stored_messages)}"
        )
        contents = [m["content"] for m in stored_messages]
        assert any("GitHub Pro" in c for c in contents), "GitHub renewal email missing"
        assert any("Acme Corp" in c for c in contents), "Offer letter email missing"
        assert any("San Francisco" in c for c in contents), "Flight email missing"

    async def test_extractor_filters_all_returns_non_memorable_message(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result(0))

            result = await store_memories_batch(ctx, "user_abc", single_email)

        assert "non-memorable" in result.lower()

    async def test_all_empty_content_emails_skipped(self, ctx):
        emails = [
            {"content": "   ", "metadata": {"subject": "A", "sender": "b@c.com"}},
            {"content": "", "metadata": {"subject": "B", "sender": "c@d.com"}},
        ]
        result = await store_memories_batch(ctx, "user_abc", emails)
        assert "No valid emails to process" in result

    async def test_missing_content_key_skipped(self, ctx):
        emails = [{"metadata": {"subject": "No Content", "sender": "x@y.com"}}]
        result = await store_memories_batch(ctx, "user_abc", emails)
        assert "No valid emails to process" in result

    async def test_message_format_includes_sender_and_subject(self, ctx):
        """Verify each message is formatted with From:/Subject: headers."""
        emails = [
            {
                "content": "Meeting at 3pm",
                "metadata": {"subject": "Sync", "sender": "boss@work.com"},
            }
        ]
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())
            await store_memories_batch(ctx, "user_abc", emails)

        content = mock_engine.retain.call_args.args[1][0]["content"]
        assert "From: boss@work.com" in content
        assert "Subject: Sync" in content
        assert "Meeting at 3pm" in content

    async def test_user_context_included_in_extraction_hints_with_name_and_email(
        self, ctx, single_email
    ):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())

            await store_memories_batch(
                ctx,
                "user_abc",
                single_email,
                user_name="Bob Jones",
                user_email="bob@example.com",
            )

        call_kwargs = mock_engine.retain.call_args.kwargs
        hints = call_kwargs["extraction_hints"]
        assert "Bob Jones" in hints
        assert "bob@example.com" in hints
        assert call_kwargs["user_name"] == "Bob Jones"

    async def test_user_context_empty_when_no_name(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())

            await store_memories_batch(ctx, "user_abc", single_email)

        hints = mock_engine.retain.call_args.kwargs["extraction_hints"]
        # No user context line when user_name is None
        assert "The user's name is" not in hints

    async def test_source_type_is_email(self, ctx, single_email):
        """retain must be called with the EMAIL source type."""
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())

            await store_memories_batch(ctx, "user_abc", single_email)

        call = mock_engine.retain.call_args
        assert call.args[0] == "user_abc"
        assert call.kwargs["source_type"] is MemorySourceType.EMAIL

    async def test_exception_in_engine_returns_error_string(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(side_effect=RuntimeError("engine is unavailable"))

            result = await store_memories_batch(ctx, "user_abc", single_email)

        assert "Error in batch memory processing" in result
        assert "user_abc" in result
        assert "engine is unavailable" in result

    async def test_mixed_valid_and_empty_content_only_valid_sent(self, ctx):
        emails = [
            {
                "content": "Valid email content here",
                "metadata": {"subject": "S1", "sender": "a@b.com"},
            },
            {"content": "", "metadata": {"subject": "S2", "sender": "c@d.com"}},
            {"content": "   ", "metadata": {"subject": "S3", "sender": "e@f.com"}},
        ]
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())

            result = await store_memories_batch(ctx, "user_abc", emails)

        # Only 1 valid email should be processed
        assert "from 1 emails" in result
        assert len(mock_engine.retain.call_args.args[1]) == 1

    async def test_missing_metadata_uses_defaults(self, ctx):
        emails = [{"content": "An email with no metadata dict at all"}]
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())
            await store_memories_batch(ctx, "user_abc", emails)

        content = mock_engine.retain.call_args.args[1][0]["content"]
        assert NO_SUBJECT in content
        assert UNKNOWN_SENDER in content

    async def test_ctx_parameter_unused_does_not_affect_result(self, single_email):
        """The ARQ ctx dict is not used — passing unusual values must not crash."""
        ctx_variants = [
            {},
            {"redis": AsyncMock()},
            {"job_id": "abc123", "score": 99},
        ]
        for ctx in ctx_variants:
            with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
                mock_engine.retain = AsyncMock(return_value=_retain_result())
                result = await store_memories_batch(ctx, "user_abc", single_email)
            assert "Extracted 1 memories" in result

    async def test_store_memories_batch_saves_all(self, ctx):
        """A batch of 5 emails must produce exactly 5 messages handed to the
        engine. If any are silently dropped, the length assertion catches it."""
        emails = [
            {
                "content": f"Email body number {i}",
                "metadata": {
                    "subject": f"Subject {i}",
                    "sender": f"sender{i}@example.com",
                },
            }
            for i in range(1, 6)
        ]

        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result(5))
            result = await store_memories_batch(ctx, "user_batch", emails)

        assert "Extracted 5 memories from 5 emails" in result

        call = mock_engine.retain.call_args
        stored_messages = call.args[1]
        assert len(stored_messages) == 5, (
            f"All 5 emails must be sent; only {len(stored_messages)} were"
        )
        for i in range(1, 6):
            matching = [m for m in stored_messages if f"Email body number {i}" in m["content"]]
            assert matching, f"Email {i} content was not handed to the engine"
        assert call.args[0] == "user_batch"

    async def test_store_memories_batch_empty(self, ctx):
        """An empty batch must return early with no engine calls at all."""
        with patch("app.workers.tasks.memory_tasks.memory_engine") as mock_engine:
            mock_engine.retain = AsyncMock(return_value=_retain_result())
            result = await store_memories_batch(ctx, "user_empty", [])

        assert "No emails to process" in result
        mock_engine.retain.assert_not_called()
