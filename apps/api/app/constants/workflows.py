"""Workflow constants."""

from enum import StrEnum


class WorkflowDelivery(StrEnum):
    """How a finished workflow run's result reaches the user.

    Failures always notify, whatever the mode: a broken workflow needs the user
    now. A run whose narration decides there is nothing worth reporting reaches
    nobody in any mode.
    """

    #: Pushed as soon as the run finishes: the user's chat platform plus the
    #: in-app completion notification.
    NOW = "now"
    #: Held as a pending brief item for the user's next brief; nothing is pushed.
    BRIEF = "brief"
    #: Kept in the workflow's conversation only; nothing is pushed.
    SILENT = "silent"


#: The ARQ task every workflow fire runs as, on whichever queue the workflow's fires take.
EXECUTE_WORKFLOW_TASK = "execute_workflow_by_id"
