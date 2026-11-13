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

    def combined_with(self, other: "WorkCancelled") -> "WorkCancelled":
        """Return both cancels as one: what a Stop's logged and unlogged halves came to."""
        return WorkCancelled(
            executor_stopped=self.executor_stopped or other.executor_stopped,
            executor_task_id=self.executor_task_id or other.executor_task_id,
            executor_spared=self.executor_spared or other.executor_spared,
            pending_task_ids=[*self.pending_task_ids, *other.pending_task_ids],
            subagent_ids=list(dict.fromkeys([*self.subagent_ids, *other.subagent_ids])),
            approval_ids=[*self.approval_ids, *other.approval_ids],
            browser_jobs={**self.browser_jobs, **other.browser_jobs},
        )

    @property
    def stopped_anything(self) -> bool:
        """Whether the stop reached any work at all."""
        return bool(
            self.executor_stopped
            or self.pending_task_ids
            or self.subagent_ids
            or self.approval_ids
            or self.browser_jobs
        )


class ConversationStopResponse(ResponseModel):
    """A conversation-level Stop: the work it stopped."""

    conversation_id: str | None = Field(
        default=None, description="The conversation stopped; None when a bot chat had none yet."
    )
    work: WorkCancelled
