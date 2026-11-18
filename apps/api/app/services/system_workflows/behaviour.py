"""How the workflow engine treats a system workflow, declared beside the workflow's definition."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from app.models.user_models import UserDocument


@dataclass(frozen=True, slots=True)
class RunAhead:
    """A job every scheduled fire enqueues to run lead before it, given the workflow id and the fire."""

    task: str
    queue: str
    lead: timedelta


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
    cron_for: Callable[[UserDocument], str] | None = None
    #: The worker queue its scheduled fires run on; None is the shared queue.
    queue: str | None = None
    #: Work each scheduled fire starts ahead of itself; None starts nothing.
    run_ahead: RunAhead | None = None


#: A workflow with no declared behaviour: every user workflow, and the integration ones.
USER_WORKFLOW_BEHAVIOUR = SystemWorkflowBehaviour()
