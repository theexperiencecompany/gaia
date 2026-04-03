"""Unit tests for memory_email_tasks ARQ worker."""

import pytest
from unittest.mock import AsyncMock, patch

from app.workers.tasks.memory_email_tasks import process_gmail_emails_to_memory


@pytest.mark.unit
class TestProcessGmailEmailsToMemory:
    """Tests for process_gmail_emails_to_memory ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    # ------------------------------------------------------------------
    # Already-processed path
    # ------------------------------------------------------------------

    async def test_already_processed_returns_early_message(self, ctx):
        """When emails were already processed, return a short-circuit message."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={"already_processed": True},
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_abc")

        assert "already processed" in result
        assert "user_abc" in result

    # ------------------------------------------------------------------
    # Successful completion path
    # ------------------------------------------------------------------

    async def test_processing_complete_returns_success_message(self, ctx):
        """When processing_complete is True, return a summary with counts."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "total": 25,
                "successful": 23,
                "failed": 2,
                "processing_complete": True,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_xyz")

        assert "completed" in result.lower()
        assert "user_xyz" in result
        assert "23/25" in result

    async def test_processing_complete_zero_total(self, ctx):
        """Zero total emails processed is still a valid complete result."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "total": 0,
                "successful": 0,
                "failed": 0,
                "processing_complete": True,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_empty")

        assert "completed" in result.lower()
        assert "0/0" in result

    async def test_processing_complete_all_successful(self, ctx):
        """All emails processed with zero failures."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "total": 10,
                "successful": 10,
                "failed": 0,
                "processing_complete": True,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_all_ok")

        assert "10/10" in result
        assert "user_all_ok" in result

    # ------------------------------------------------------------------
    # Incomplete / failure path
    # ------------------------------------------------------------------

    async def test_processing_incomplete_returns_failure_message(self, ctx):
        """When processing_complete is False, return a failure message."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "total": 20,
                "successful": 15,
                "failed": 5,
                "processing_complete": False,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_partial")

        assert "failed" in result.lower()
        assert "user_partial" in result
        assert "15/20" in result
        assert "5 failed" in result

    async def test_processing_incomplete_all_failed(self, ctx):
        """All emails fail — message reflects total failure."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "total": 8,
                "successful": 0,
                "failed": 8,
                "processing_complete": False,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_allfail")

        assert "failed" in result.lower()
        assert "0/8" in result
        assert "8 failed" in result

    # ------------------------------------------------------------------
    # Missing keys in result dict — default to 0
    # ------------------------------------------------------------------

    async def test_missing_keys_default_to_zero(self, ctx):
        """When result dict has no total/successful/failed keys, default to 0."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "already_processed": False,
                "processing_complete": True,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_nokeys")

        # Should still succeed with 0/0
        assert "completed" in result.lower()
        assert "0/0" in result

    # ------------------------------------------------------------------
    # Exception propagation
    # ------------------------------------------------------------------

    async def test_exception_in_processor_propagates(self, ctx):
        """Unhandled exceptions from process_gmail_to_memory propagate."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Gmail API down"),
        ):
            with pytest.raises(RuntimeError, match="Gmail API down"):
                await process_gmail_emails_to_memory(ctx, "user_error")

    async def test_connection_error_propagates(self, ctx):
        """Network errors from the processor are not swallowed."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Cannot reach Gmail"),
        ):
            with pytest.raises(ConnectionError, match="Cannot reach Gmail"):
                await process_gmail_emails_to_memory(ctx, "user_net")

    # ------------------------------------------------------------------
    # ARQ ctx parameter
    # ------------------------------------------------------------------

    async def test_ctx_parameter_does_not_affect_result(self):
        """The ARQ ctx dict is unused — different values must not crash."""
        ctx_variants = [
            {},
            {"redis": AsyncMock()},
            {"job_id": "abc123", "score": 42},
        ]
        for ctx in ctx_variants:
            with patch(
                "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
                new_callable=AsyncMock,
                return_value={
                    "already_processed": False,
                    "total": 1,
                    "successful": 1,
                    "failed": 0,
                    "processing_complete": True,
                },
            ):
                result = await process_gmail_emails_to_memory(ctx, "user_ctx")
            assert "completed" in result.lower()

    # ------------------------------------------------------------------
    # Edge: already_processed key missing (defaults to False)
    # ------------------------------------------------------------------

    async def test_already_processed_key_missing_defaults_false(self, ctx):
        """When already_processed is absent, .get() returns False and we
        proceed to the count-based branch."""
        with patch(
            "app.workers.tasks.memory_email_tasks.process_gmail_to_memory",
            new_callable=AsyncMock,
            return_value={
                "total": 5,
                "successful": 5,
                "failed": 0,
                "processing_complete": True,
            },
        ):
            result = await process_gmail_emails_to_memory(ctx, "user_nokey")

        assert "completed" in result.lower()
        assert "5/5" in result
