"""Unit tests for app.workers.tasks.onboarding_tasks.

The two ARQ tasks run the onboarding intelligence pipeline (full mode) and the
split pipeline's completing phase. Each captures ``onboarding:completed`` only
when the persisted phase actually reached PERSONALIZATION_COMPLETE — a task
returning success is not completion (aborted runs and split-mode early jobs
succeed without finishing onboarding).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.user_models import OnboardingPhase
from app.services.analytics_service import AnalyticsEvents
from app.workers.tasks.onboarding_tasks import (
    process_onboarding_intelligence_task,
    process_onboarding_workflows_task,
)

MODULE = "app.workers.tasks.onboarding_tasks"
PIPELINE = "app.services.onboarding.intelligence_service"


def _doc(phase: OnboardingPhase, pipeline_mode: str = "full") -> MagicMock:
    doc = MagicMock()
    doc.onboarding = {"phase": phase, "pipeline_mode": pipeline_mode}
    return doc


class TestIntelligenceTaskAnalytics:
    async def test_captures_when_pipeline_completed(self) -> None:
        with (
            patch(f"{PIPELINE}.process_onboarding_intelligence", new_callable=AsyncMock),
            patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock) as get,
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            get.return_value = _doc(OnboardingPhase.PERSONALIZATION_COMPLETE, "full")
            result = await process_onboarding_intelligence_task({}, "user-1")

        assert "completed" in result
        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[0] == "user-1"
        assert mock_capture.call_args.args[1] == AnalyticsEvents.ONBOARDING_COMPLETED
        assert mock_capture.call_args.args[2] == {"pipeline_mode": "full"}

    async def test_skips_when_pipeline_not_completed(self) -> None:
        """Split-mode early jobs (and aborts) succeed without completing."""
        with (
            patch(f"{PIPELINE}.process_onboarding_intelligence", new_callable=AsyncMock),
            patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock) as get,
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            get.return_value = _doc(OnboardingPhase.PERSONALIZATION_PENDING, "split")
            result = await process_onboarding_intelligence_task({}, "user-1")

        assert "completed" in result
        mock_capture.assert_not_called()

    async def test_doc_read_failure_skips_event_and_keeps_success(self) -> None:
        """A DB read failure for analytics must not break the task result."""
        with (
            patch(f"{PIPELINE}.process_onboarding_intelligence", new_callable=AsyncMock),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            result = await process_onboarding_intelligence_task({}, "user-1")

        assert "completed" in result
        mock_capture.assert_not_called()


class TestWorkflowsTaskAnalytics:
    async def test_captures_when_pipeline_completed(self) -> None:
        with (
            patch(f"{PIPELINE}.process_onboarding_workflows_phase", new_callable=AsyncMock),
            patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock) as get,
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            get.return_value = _doc(OnboardingPhase.PERSONALIZATION_COMPLETE, "split")
            result = await process_onboarding_workflows_task({}, "user-1")

        assert "completed" in result
        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[0] == "user-1"
        assert mock_capture.call_args.args[1] == AnalyticsEvents.ONBOARDING_COMPLETED
        assert mock_capture.call_args.args[2] == {"pipeline_mode": "split"}

    async def test_skips_when_pipeline_not_completed(self) -> None:
        with (
            patch(f"{PIPELINE}.process_onboarding_workflows_phase", new_callable=AsyncMock),
            patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock) as get,
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            get.return_value = _doc(OnboardingPhase.PERSONALIZATION_PENDING, "split")
            result = await process_onboarding_workflows_task({}, "user-1")

        assert "completed" in result
        mock_capture.assert_not_called()

    async def test_pipeline_failure_never_captures(self) -> None:
        """The failure path returns early — no completion read, no event."""
        with (
            patch(
                f"{PIPELINE}.process_onboarding_workflows_phase",
                new_callable=AsyncMock,
                side_effect=RuntimeError("pipeline down"),
            ),
            patch(f"{MODULE}.user_repository.get", new_callable=AsyncMock),
            patch(f"{MODULE}.user_repository.set_pipeline_completion", new_callable=AsyncMock),
            patch(f"{MODULE}.capture_event") as mock_capture,
            patch(f"{MODULE}.log"),
        ):
            result = await process_onboarding_workflows_task({}, "user-1")

        assert "failed" in result
        mock_capture.assert_not_called()
