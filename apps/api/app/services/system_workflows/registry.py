"""Every system workflow's declared behaviour, by system_workflow_key, as the engine reads it."""

from app.services.system_workflows.behaviour import (
    USER_WORKFLOW_BEHAVIOUR,
    SystemWorkflowBehaviour,
)
from app.services.system_workflows.definitions.briefing import BRIEFING_BEHAVIOURS

_BEHAVIOURS: dict[str, SystemWorkflowBehaviour] = {**BRIEFING_BEHAVIOURS}

#: The workflows a user's list and count leave out.
UNLISTED_KEYS: frozenset[str] = frozenset(k for k, b in _BEHAVIOURS.items() if not b.listed)
#: The workflows no system pause (dormancy, lapsed plan, lost integration) switches off.
UNPAUSABLE_KEYS: frozenset[str] = frozenset(k for k, b in _BEHAVIOURS.items() if not b.pausable)


def behaviour_of(system_workflow_key: str | None) -> SystemWorkflowBehaviour:
    """Return how the engine treats the workflow under system_workflow_key; a user's for None."""
    if system_workflow_key is None:
        return USER_WORKFLOW_BEHAVIOUR
    return _BEHAVIOURS.get(system_workflow_key, USER_WORKFLOW_BEHAVIOUR)
