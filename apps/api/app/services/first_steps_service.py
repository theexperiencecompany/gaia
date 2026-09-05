"""Activation checklist (first-steps widget) progress.

Progress derives from real signals — a stated goal, integration connects,
platform links, the first Approve — never self-report. Steps satisfied before
the widget ever rendered are pre-checked on first read so long-time users
aren't asked to redo history.
"""

from datetime import UTC, datetime
from typing import Any

from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.models.todo_models import ExecutionStatus
from app.services.briefing.context import has_meaningful_focus
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


async def hide_step(user_id: str, step: str) -> None:
    """Hide a single checklist row server-side (persists across browsers)."""
    if step not in ALL_STEPS:
        return
    await user_repository.add_hidden_first_step(user_id, step)


async def get_steps(user_id: str) -> dict[str, Any]:
    """Current progress, pre-checking steps already satisfied by existing state."""
    user = await user_repository.get(user_id)
    steps: dict[str, Any] = dict((user.first_steps if user else None) or {})
    now = datetime.now(UTC)

    if STEP_TELL_GAIA_GOAL not in steps:
        # A real onboarding goal, or any goal-kind todo, counts as "told GAIA".
        focus = ((user.onboarding if user else None) or {}).get("focus")
        has_goal_todo = await todo_repository.has_goal_todo(user_id)
        if has_meaningful_focus(focus) or has_goal_todo:
            await mark_step(user_id, STEP_TELL_GAIA_GOAL)
            steps[STEP_TELL_GAIA_GOAL] = now

    if STEP_LINK_PLATFORM not in steps:
        # Any linked chat platform satisfies the step retroactively.
        links = (user.platform_links if user else None) or {}
        if any(isinstance(v, dict) and v.get("id") for v in links.values()):
            await mark_step(user_id, STEP_LINK_PLATFORM)
            steps[STEP_LINK_PLATFORM] = now

    if STEP_CONNECT_INTEGRATION not in steps:
        # Any connected non-Gmail integration satisfies the step retroactively.
        connected = await user_integration_repository.find_connected_excluding(
            user_id, _NON_ACTIVATION_INTEGRATION
        )
        if connected:
            await mark_step(user_id, STEP_CONNECT_INTEGRATION)
            steps[STEP_CONNECT_INTEGRATION] = now

    # The first_approve row is uncompletable until a proposal has ever existed,
    # so the frontend hides it until this is true.
    has_had_proposal = bool(
        steps.get(STEP_FIRST_APPROVE)
    ) or await todo_repository.has_gaia_execution_history(
        user_id, statuses=list(_PROPOSAL_HISTORY_STATUSES)
    )

    hidden_steps = [s for s in (steps.get("hidden_steps") or []) if s in ALL_STEPS]

    return {
        "steps": {step: steps[step].isoformat() if steps.get(step) else None for step in ALL_STEPS},
        "hidden_steps": hidden_steps,
        "has_had_proposal": has_had_proposal,
        "dismissed": STEP_DISMISSED_ALL in steps,
    }
