"""Unit tests for the nurture email ARQ task (app/workers/tasks/nurture_tasks.py).

The task is a pure delegation envelope: it hands control to the nurture
sequence service and returns the service's verdict string verbatim. The
service's own logic (frequency caps, step selection, send path, candidate
sweep) is pinned in tests/unit/services/test_nurture_service.py — here we
mock that seam and pin the task's contract: exact passthrough of the verdict,
no arguments forwarded, no ctx influence, and error propagation.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.nurture_tasks import run_nurture_sequence_task


class TestRunNurtureSequenceTask:
    """Tests for the run_nurture_sequence_task ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_returns_service_verdict_verbatim(self, ctx):
        with patch(
            "app.workers.tasks.nurture_tasks.run_nurture_sequence",
            new_callable=AsyncMock,
            return_value="nurture: sent 3 of 42 candidates",
        ) as mock_service:
            result = await run_nurture_sequence_task(ctx)

        assert result == "nurture: sent 3 of 42 candidates"
        mock_service.assert_awaited_once()

    async def test_delegates_to_service_with_no_arguments(self, ctx):
        """The service must be awaited exactly once, with neither args nor kwargs."""
        with patch(
            "app.workers.tasks.nurture_tasks.run_nurture_sequence",
            new_callable=AsyncMock,
            return_value="nurture: sent 1 of 1 candidates",
        ) as mock_service:
            await run_nurture_sequence_task(ctx)

        mock_service.assert_awaited_once_with()

    async def test_skipped_verdict_passthrough(self, ctx):
        """The not-configured verdict produced by the service must surface unchanged."""
        with patch(
            "app.workers.tasks.nurture_tasks.run_nurture_sequence",
            new_callable=AsyncMock,
            return_value="skipped: email not configured",
        ):
            result = await run_nurture_sequence_task(ctx)

        assert result == "skipped: email not configured"

    async def test_zero_sent_verdict_passthrough(self, ctx):
        """Proves the task does not reformat or re-interpolate the verdict string."""
        with patch(
            "app.workers.tasks.nurture_tasks.run_nurture_sequence",
            new_callable=AsyncMock,
            return_value="nurture: sent 0 of 0 candidates",
        ):
            result = await run_nurture_sequence_task(ctx)

        assert result == "nurture: sent 0 of 0 candidates"

    async def test_service_exception_propagates(self, ctx):
        """A service failure must surface to the ARQ envelope, never be swallowed."""
        with patch(
            "app.workers.tasks.nurture_tasks.run_nurture_sequence",
            new_callable=AsyncMock,
            side_effect=RuntimeError("MongoDB unavailable"),
        ):
            with pytest.raises(RuntimeError, match="MongoDB unavailable"):
                await run_nurture_sequence_task(ctx)

    async def test_ctx_is_unused_and_never_forwarded(self):
        """The ARQ ctx is accepted but must not affect the outcome or the service call."""
        for ctx in [{}, {"redis": AsyncMock(), "job_id": "j1"}]:
            with patch(
                "app.workers.tasks.nurture_tasks.run_nurture_sequence",
                new_callable=AsyncMock,
                return_value="nurture: sent 2 of 5 candidates",
            ) as mock_service:
                result = await run_nurture_sequence_task(ctx)

            assert result == "nurture: sent 2 of 5 candidates"
            mock_service.assert_awaited_once_with()
