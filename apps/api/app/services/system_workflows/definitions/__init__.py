"""The built-in workflows GAIA provisions for an integration, by integration id.

This is the one registry both the provisioner and the comms prompt read: what
gets created on connect is exactly what GAIA describes to the user.
"""

from collections.abc import Callable

from app.models.workflow_models import CreateWorkflowRequest
from app.services.system_workflows.definitions.calendar import CALENDAR_SYSTEM_WORKFLOWS
from app.services.system_workflows.definitions.gmail import GMAIL_SYSTEM_WORKFLOWS

SYSTEM_WORKFLOWS_BY_INTEGRATION: dict[
    str, list[tuple[str, Callable[[], CreateWorkflowRequest]]]
] = {
    "gmail": GMAIL_SYSTEM_WORKFLOWS,
    "googlecalendar": CALENDAR_SYSTEM_WORKFLOWS,
}
