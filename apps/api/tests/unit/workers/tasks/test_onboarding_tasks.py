"""Unit tests for app.workers.tasks.onboarding_tasks.

One task remains: the Gmail personalization pipeline, enqueued when a user
connects Gmail. It owns exactly two things beyond calling the pipeline —
releasing the job slot, and reporting the outcome. It deliberately owns neither
the onboarding phase (completion is written when the form is submitted) nor the
``onboarding:completed`` analytics event (captured by ``complete_onboarding``).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.onboarding import INTELLIGENCE_JOB_FIELD
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


class TestTheJobSlotIsReleased:
    async def test_the_slot_is_cleared_with_this_jobs_id(self, pipeline: AsyncMock) -> None:
        """Compare-and-clear on our own id — a stale id makes the next reset try
        to abort a job that finished long ago."""
        repo = AsyncMock()
        with patch("app.services.onboarding.intelligence_job.user_repository", repo):
            await process_onboarding_intelligence_task({"job_id": "job-7"}, USER)

        repo.clear_active_job_if_matches.assert_awaited_once_with(
            USER, INTELLIGENCE_JOB_FIELD, "job-7"
        )

    async def test_the_slot_is_cleared_after_a_failed_pipeline_too(
        self, pipeline: AsyncMock
    ) -> None:
        """Left set, a crashed run blocks every later reconnect from enqueueing."""
        pipeline.side_effect = RuntimeError("boom")
        repo = AsyncMock()

        with patch("app.services.onboarding.intelligence_job.user_repository", repo):
            result = await process_onboarding_intelligence_task({"job_id": "job-7"}, USER)

        repo.clear_active_job_if_matches.assert_awaited_once_with(
            USER, INTELLIGENCE_JOB_FIELD, "job-7"
        )
        assert "failed" in result

    async def test_nothing_is_cleared_when_arq_supplied_no_job_id(
        self, pipeline: AsyncMock
    ) -> None:
        with patch(f"{MODULE}.clear_active_intelligence_job", new_callable=AsyncMock) as clear:
            await process_onboarding_intelligence_task({}, USER)

        clear.assert_not_awaited()

    async def test_a_failed_clear_does_not_lose_the_success_result(
        self, pipeline: AsyncMock
    ) -> None:
        with (
            patch(
                f"{MODULE}.clear_active_intelligence_job",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            result = await process_onboarding_intelligence_task({"job_id": "job-7"}, USER)

        assert result == f"Gmail personalization completed for user {USER}"
        assert log.warning.call_args.kwargs["job_id"] == "job-7"
        assert log.warning.call_args.kwargs["error"] == "mongo down"


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
        repo.set_pipeline_completion.assert_not_awaited()
        repo.complete_onboarding.assert_not_awaited()

    async def test_no_completion_event_is_captured_here(self, pipeline: AsyncMock) -> None:
        """``complete_onboarding`` emits the milestone. A second emitter would
        count every Gmail connect as another onboarding completion."""
        with patch("app.services.analytics_service.capture_event") as capture:
            await process_onboarding_intelligence_task({}, USER)

        capture.assert_not_called()
