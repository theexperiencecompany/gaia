"""Unit tests for memory_tasks ARQ worker."""

import pytest
from unittest.mock import AsyncMock, patch

from app.workers.tasks.memory_tasks import store_memories_batch


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
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            result = await store_memories_batch(
                ctx,
                "user_abc",
                single_email,
                user_name="Alice Smith",
                user_email="alice@example.com",
            )

        assert "Stored 1 emails in mem0 successfully" in result
        mock_svc.store_memory_batch.assert_called_once()
        # Verify the actual memory content stored, not just the return string.
        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        stored_messages = call_kwargs["messages"]
        assert len(stored_messages) == 1
        assert stored_messages[0]["role"] == "user"
        assert "Conference Acceptance" in stored_messages[0]["content"]
        assert "no-reply@pycon.org" in stored_messages[0]["content"]
        assert "Python conference" in stored_messages[0]["content"]

    async def test_batch_stored_successfully(self, ctx, multi_email_batch):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            result = await store_memories_batch(
                ctx,
                "user_abc",
                multi_email_batch,
                user_name="Alice Smith",
                user_email="alice@example.com",
            )

        assert "Stored 3 emails in mem0 successfully" in result
        # Verify all 3 memory objects were actually constructed and passed.
        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        stored_messages = call_kwargs["messages"]
        assert len(stored_messages) == 3, (
            f"Expected 3 memory objects in DB call, got {len(stored_messages)}"
        )
        contents = [m["content"] for m in stored_messages]
        assert any("GitHub Pro" in c for c in contents), "GitHub renewal email missing"
        assert any("Acme Corp" in c for c in contents), "Offer letter email missing"
        assert any("San Francisco" in c for c in contents), "Flight email missing"

    async def test_mem0_filters_all_returns_non_memorable_message(
        self, ctx, single_email
    ):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=False)

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
        captured_messages = []

        async def capture_call(**kwargs):
            captured_messages.extend(kwargs.get("messages", []))
            return True

        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(side_effect=capture_call)
            await store_memories_batch(ctx, "user_abc", emails)

        assert len(captured_messages) == 1
        content = captured_messages[0]["content"]
        assert "From: boss@work.com" in content
        assert "Subject: Sync" in content
        assert "Meeting at 3pm" in content

    async def test_user_context_included_in_custom_instructions_with_name_and_email(
        self, ctx, single_email
    ):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            await store_memories_batch(
                ctx,
                "user_abc",
                single_email,
                user_name="Bob Jones",
                user_email="bob@example.com",
            )

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        instructions = call_kwargs["custom_instructions"]
        assert "Bob Jones" in instructions
        assert "bob@example.com" in instructions

    async def test_user_context_empty_when_no_name(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            await store_memories_batch(ctx, "user_abc", single_email)

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        instructions = call_kwargs["custom_instructions"]
        # No user context line when user_name is None
        assert "The user's name is" not in instructions

    async def test_metadata_passed_to_service_contains_source(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            await store_memories_batch(ctx, "user_abc", single_email, user_name="Alice")

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        assert call_kwargs["metadata"]["source"] == "gmail_background_batch"
        assert call_kwargs["metadata"]["batch_size"] == 1
        assert call_kwargs["user_id"] == "user_abc"

    async def test_async_mode_is_false(self, ctx, single_email):
        """store_memory_batch must be called with async_mode=False."""
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            await store_memories_batch(ctx, "user_abc", single_email)

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        assert call_kwargs["async_mode"] is False

    async def test_exception_in_service_returns_error_string(self, ctx, single_email):
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(
                side_effect=RuntimeError("Mem0 is unavailable")
            )

            result = await store_memories_batch(ctx, "user_abc", single_email)

        assert "Error in batch memory processing" in result
        assert "user_abc" in result
        assert "Mem0 is unavailable" in result

    async def test_mixed_valid_and_empty_content_only_valid_sent(self, ctx):
        emails = [
            {
                "content": "Valid email content here",
                "metadata": {"subject": "S1", "sender": "a@b.com"},
            },
            {"content": "", "metadata": {"subject": "S2", "sender": "c@d.com"}},
            {"content": "   ", "metadata": {"subject": "S3", "sender": "e@f.com"}},
        ]
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)

            result = await store_memories_batch(ctx, "user_abc", emails)

        # Only 1 valid email should be processed
        assert "Stored 1 emails in mem0 successfully" in result
        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        assert len(call_kwargs["messages"]) == 1

    async def test_missing_metadata_uses_defaults(self, ctx):
        emails = [{"content": "An email with no metadata dict at all"}]
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)
            await store_memories_batch(ctx, "user_abc", emails)

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        content = call_kwargs["messages"][0]["content"]
        assert "[No Subject]" in content
        assert "[Unknown Sender]" in content

    async def test_ctx_parameter_unused_does_not_affect_result(self, single_email):
        """The ARQ ctx dict is not used — passing unusual values must not crash."""
        ctx_variants = [
            {},
            {"redis": AsyncMock()},
            {"job_id": "abc123", "score": 99},
        ]
        for ctx in ctx_variants:
            with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
                mock_svc.store_memory_batch = AsyncMock(return_value=True)
                result = await store_memories_batch(ctx, "user_abc", single_email)
            assert "Stored 1 emails" in result

    async def test_store_memories_batch_saves_all(self, ctx):
        """A batch of 5 emails must produce exactly 5 memory objects written to
        the DB (via store_memory_batch).  If any are silently dropped, the
        assertion on stored_messages length will catch it."""
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

        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)
            result = await store_memories_batch(ctx, "user_batch", emails)

        assert "Stored 5 emails in mem0 successfully" in result

        call_kwargs = mock_svc.store_memory_batch.call_args.kwargs
        stored_messages = call_kwargs["messages"]
        assert len(stored_messages) == 5, (
            f"All 5 emails must be saved; only {len(stored_messages)} were stored"
        )
        for i in range(1, 6):
            matching = [
                m for m in stored_messages if f"Email body number {i}" in m["content"]
            ]
            assert matching, f"Email {i} content was not saved to the DB"
        assert call_kwargs["user_id"] == "user_batch"

    async def test_store_memories_batch_empty(self, ctx):
        """An empty batch must return early with no DB writes at all."""
        with patch("app.workers.tasks.memory_tasks.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)
            result = await store_memories_batch(ctx, "user_empty", [])

        assert "No emails to process" in result
        # No DB write should have happened.
        mock_svc.store_memory_batch.assert_not_called()
