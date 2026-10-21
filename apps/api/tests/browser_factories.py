"""Browser-job test factories, apart from tests/factories.py so suites that never touch a browser job never import its schema."""

from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus


def make_browser_job_state(
    job_id: str = "job-1",
    *,
    status: BrowserJobStatus = BrowserJobStatus.RUNNING,
    task: str = "t",
    conversation_id: str = "conv-1",
    user_id: str = "u1",
    in_background: bool = True,
) -> BrowserJobState:
    """Build the state of a browser job that has not ended, as browser_task queues it."""
    request = BrowserJobRequest(
        job_id=job_id,
        tool_call_id=f"call-{job_id}",
        user_id=user_id,
        conversation_id=conversation_id,
        task=task,
        in_background=in_background,
    )
    return BrowserJobState.of(request, status)
