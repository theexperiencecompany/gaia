"""What a workflow run's prompt reads off the trigger that fired it."""

from pydantic import BaseModel, ConfigDict, Field

from app.constants.agents import PLAYBOOK_FALLBACK_CONTEXT_KEY
from app.models.trigger_gate_models import QuietHoursStamp


class TriggerEmailData(BaseModel):
    """The ``email_data`` of a Gmail-triggered run, as the prompt reads it."""

    model_config = ConfigDict(extra="ignore")

    sender: str = "Unknown"
    subject: str = "No Subject"
    message_text: str = ""


class WorkflowTriggerContext(BaseModel):
    """The keys ``format_workflow_execution_message`` reads off a run's trigger context.

    The bag itself is open by construction — schedulers spread arbitrary provider
    trigger data through it alongside the agent's own keys — so this is a view of
    it, parsed once here, not its full shape.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    tracked_todos_context: str = ""
    workflow_id: str | None = None
    workflow_notify_on_completion: bool = True
    playbook_fallback: str | None = Field(
        default=None, validation_alias=PLAYBOOK_FALLBACK_CONTEXT_KEY
    )
    type: str | None = None
    email_data: TriggerEmailData = Field(default_factory=TriggerEmailData)
    triggered_at: str = "Unknown"
    # Provider payload of a trigger-fired run: open shape, read via _event_accounts.
    trigger_data: dict[str, object] = Field(default_factory=dict)
    quiet_hours: QuietHoursStamp | None = None
