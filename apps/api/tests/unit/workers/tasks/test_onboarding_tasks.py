"""Unit tests for app.workers.tasks.onboarding_tasks.

One task remains: the Gmail personalization pipeline, enqueued when a user
connects Gmail. It owns exactly one thing beyond calling the pipeline:
reporting the outcome. It deliberately owns neither the onboarding phase
(completion is written when the form is submitted) nor the
``onboarding:completed`` analytics event (captured by ``complete_onboarding``).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.onboarding_tasks import process_onboarding_intelligence_task

MODULE = "app.workers.tasks.onboarding_tasks"
PIPELINE = "app.services.onboarding.intelligence_service"

USER = "user-1"


@pytest.fixture
def pipeline() -> AsyncMock:
    with patch(f"{PIPELINE}.process_onboarding_intelligence", new_callable=AsyncMock) as mock:
        yield mock


class TestTheTaskRunsThePipeline:
    async def test_success_calls_the_pipeline_and_reports_the_user(
        self, pipeline: AsyncMock
    ) -> None:
        result = await process_onboarding_intelligence_task({}, USER)

        pipeline.assert_awaited_once_with(USER)
        assert result == f"Gmail personalization completed for user {USER}"

    async def test_a_pipeline_failure_is_reported_not_raised(self, pipeline: AsyncMock) -> None:
        """ARQ retries on an exception; this pipeline is not idempotent enough to
        be retried blindly, so the failure comes back as a job result string."""
        pipeline.side_effect = RuntimeError("LLM timeout")

        result = await process_onboarding_intelligence_task({}, USER)

        assert result == f"Gmail personalization failed for user {USER}: LLM timeout"


class TestTheTaskOwnsNeitherThePhaseNorTheEvent:
    async def test_a_crashed_pipeline_does_not_rescue_the_onboarding_phase(
        self, pipeline: AsyncMock
    ) -> None:
        """Onboarding is already complete before this job ever runs, so a rescue
        write here would silently overwrite whatever phase the user is really in."""
        pipeline.side_effect = RuntimeError("boom")
        repo = AsyncMock()

        with patch("app.db.repositories.users.user_repository", repo):
            await process_onboarding_intelligence_task({}, USER)

        repo.set_onboarding_phase.assert_not_awaited()
        repo.complete_onboarding.assert_not_awaited()

    async def test_no_completion_event_is_captured_here(self, pipeline: AsyncMock) -> None:
        """``complete_onboarding`` emits the milestone. A second emitter would
        count every Gmail connect as another onboarding completion."""
        with patch("app.services.analytics_service.capture_event") as capture:
            await process_onboarding_intelligence_task({}, USER)

        capture.assert_not_called()
