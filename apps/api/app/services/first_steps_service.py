"""Activation checklist (first-steps widget) progress.

Progress derives from real signals — a stated goal, integration connects,
platform links, the first Approve — never self-report. Steps satisfied before
the widget ever rendered are pre-checked on first read so long-time users
aren't asked to redo history.
"""

from app.db.repositories.users import user_repository
from app.models.todo_models import ExecutionStatus
from app.utils.analytics import track

STEP_TELL_GAIA_GOAL = "tell_gaia_goal"
STEP_CONNECT_INTEGRATION = "connect_integration"
STEP_LINK_PLATFORM = "link_platform"
STEP_FIRST_APPROVE = "first_approve"
STEP_DISMISSED_ALL = "dismissed_all"

ALL_STEPS: tuple[str, ...] = (
    STEP_TELL_GAIA_GOAL,
    STEP_CONNECT_INTEGRATION,
    STEP_LINK_PLATFORM,
    STEP_FIRST_APPROVE,
)
_VALID_STEPS: frozenset[str] = frozenset((*ALL_STEPS, STEP_DISMISSED_ALL))

# A proposal is any GAIA todo that entered the approval lifecycle. queued/running
# work never needs a tap, so it doesn't imply the user has anything to approve.
_PROPOSAL_HISTORY_STATUSES = (
    ExecutionStatus.PROPOSED.value,
    ExecutionStatus.DISMISSED.value,
    ExecutionStatus.EXPIRED.value,
)

# Any integration but Gmail (connected at signup, not a deliberate activation
# signal) counts as "connected something real".
_NON_ACTIVATION_INTEGRATION = "gmail"


async def mark_step(user_id: str, step: str) -> None:
    """Idempotently record a step completion (no-op on repeats or unknown steps)."""
    if step not in _VALID_STEPS:
        return
    if await user_repository.set_first_step(user_id, step):
        track(user_id, "first_steps_step_done", {"step": step})
