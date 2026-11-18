"""How the workflow engine treats a system workflow, declared beside the workflow's definition."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.models.user_models import UserDocument


@dataclass(frozen=True, slots=True)
class SystemWorkflowBehaviour:
    """What sets a system workflow apart from a user's; the defaults are a user workflow's."""

    #: Shown and counted among the user's workflows.
    listed: bool = True
    #: A failed run tells the user.
    notify_on_failure: bool = True
    #: The dormancy, lapsed-plan and disconnected-integration pauses may switch it off.
    pausable: bool = True
    #: The cron the user's own copy runs on, from the user; None keeps the definition's.
    cron_for: Callable[[UserDocument], Awaitable[str]] | None = None


#: A workflow with no declared behaviour: every user workflow, and the integration ones.
USER_WORKFLOW_BEHAVIOUR = SystemWorkflowBehaviour()
