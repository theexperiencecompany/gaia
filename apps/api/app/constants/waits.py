"""Waits: something GAIA asked the user to do, and who to pick back up once it is done."""

from datetime import timedelta
from enum import StrEnum
from typing import Final

from app.constants.cache import ONE_DAY_TTL


class WaitCondition(StrEnum):
    """What the user was asked to do; the subject id names which one."""

    #: subject: the integration id.
    INTEGRATION_CONNECTED = "integration_connected"
    #: subject: the workflow id, or the draft id of a workflow not created yet.
    WORKFLOW_TRIGGER_CONFIGURED = "workflow_trigger_configured"


class WaiterKind(StrEnum):
    """What gets picked back up; the waiter id names which one."""

    #: waiter id: the conversation id.
    CHAT = "chat"
    #: waiter id: the tracked todo id.
    TODO = "todo"
    #: waiter id: the workflow id.
    WORKFLOW = "workflow"


#: How long an unanswered ask keeps its waiter, counted from the latest ask.
WAIT_TTL_SECONDS: Final = 7 * ONE_DAY_TTL
#: The worker job that picks one waiter back up.
RESUME_WAITER_TASK: Final = "resume_waiter"
#: Tries before a resume that keeps failing gives up, leaving its wait for the next report.
RESUME_WAITER_MAX_TRIES: Final = 5
#: How long a resume job holds its claimed wait; past it, a job that died mid-resume loses it.
RESUME_WAITER_LEASE: Final = timedelta(hours=1)
#: First retry delay of a failed resume; each later try doubles it.
RESUME_WAITER_RETRY_DELAY: Final = timedelta(seconds=30)
#: The synthetic trigger name a woken tracked todo run sees as its origin.
WAIT_MET_TRIGGER: Final = "gaia_wait_met"
#: The workflow run context key carrying why the run was started.
WAIT_MET_CONTEXT_KEY: Final = "wait_met"
