"""What stopping a conversation's work came to: the executor run, its inbox, subagents, approvals, browser jobs."""

from pydantic import Field

from app.constants.browser import BrowserStopOutcome
from app.schemas.common import ResponseModel


class WorkCancelled(ResponseModel):
    """Everything one stop cancelled; all empty when the conversation was idle."""

    executor_stopped: bool = Field(
        default=False, description="A running executor task was stopped."
    )
    executor_task_id: str | None = Field(
        default=None,
        description="Task id of the stopped executor run; None for a lock without one.",
    )
    executor_spared: bool = Field(
        default=False, description="An executor task kept running because the stop did not name it."
    )
    pending_tasks: int = Field(default=0, description="Queued executor requests dropped wholesale.")
    pending_task_ids: list[str] = Field(
        default_factory=list, description="Queued executor requests dropped by id."
    )
    subagent_ids: list[str] = Field(default_factory=list, description="Running subagents stopped.")
    approval_ids: list[str] = Field(
        default_factory=list, description="Pending approvals closed, barrier and ledger."
    )
    browser_jobs: dict[str, BrowserStopOutcome] = Field(
        default_factory=dict, description="Browser jobs reached, with what each stop came to."
    )

    @property
    def stopped_anything(self) -> bool:
        """Whether the stop reached any work at all."""
        return bool(
            self.executor_stopped
            or self.pending_tasks
            or self.pending_task_ids
            or self.subagent_ids
            or self.approval_ids
            or self.browser_jobs
        )


class ConversationStopResponse(ResponseModel):
    """A conversation-level Stop: the live streams it cancelled and the work it stopped."""

    conversation_id: str | None = Field(
        default=None, description="The conversation stopped; None when a bot chat had none yet."
    )
    stream_ids: list[str] = Field(default_factory=list, description="Live streams cancelled.")
    work: WorkCancelled
