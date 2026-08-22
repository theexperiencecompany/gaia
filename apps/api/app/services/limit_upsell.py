"""Fire-and-forget upsell side effects when a FREE user hits a usage wall.

Called from the two exceed seams — the tiered rate limiter (covers every
decorated endpoint and agent tool) and the daily cost-budget gate — so every
wall a free user can hit produces one analytics event and, at most once a
week (deduped in the senders), one email. ``origin`` picks the email: an
interactive hit (the user did something and was blocked) gets the upsell
pitch; a background hit (a workflow run the user never initiated) gets an
informative "your workflows are taking a break" email instead — telling a
user who hasn't touched the app that *they* hit *their* limit reads as a bug.
Never blocks or raises into the caller: losing a marketing email must not
affect the 429 itself.
"""

from contextvars import ContextVar
from enum import StrEnum

from app.models.payment_models import PlanType
from app.services.analytics_service import capture_event
from app.services.email.senders import (
    send_limit_reached_email,
    send_workflows_paused_email,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log


class LimitHitOrigin(StrEnum):
    """Who ran into the wall: the user directly, or a background run."""

    INTERACTIVE = "interactive"
    BACKGROUND = "background"


#: The origin of the work running right now. Set once at a run's boundary
#: (see ``limit_origin``) and read by every limit seam, because the seam that
#: trips is usually several frames below the code that knows why it is running:
#: an agent tool inside a background workflow used to report the run as
#: interactive and mail the user "you hit your limit" for work they never
#: started. INTERACTIVE is the right default — a request with nobody marking it
#: is a user standing there.
_run_origin: ContextVar[LimitHitOrigin] = ContextVar(
    "limit_hit_origin", default=LimitHitOrigin.INTERACTIVE
)


def current_limit_origin() -> LimitHitOrigin:
    """Whether the work running right now was started by the user or by GAIA."""
    return _run_origin.get()


def mark_run_origin(origin: LimitHitOrigin) -> None:
    """Declare what kind of work the CURRENT task is doing.

    Covers everything the task reaches afterwards — the agent, its tools, and
    any task spawned from here, since a task copies the context it is created
    in. Scoped to the task rather than a block: arq runs each job as its own
    task (``loop.create_task(function.coroutine(...))``), so a job cannot leak
    its origin into the next one, and marking a whole run needs no ``with``
    around its body — indentation that would otherwise drag every wrapped line
    into the diff.

    Tests share one task, so the suite resets it between cases.
    """
    _run_origin.set(origin)


def schedule_limit_upsell(
    user_id: str, feature_key: str, user_plan: PlanType, origin: LimitHitOrigin
) -> None:
    """Queue the limit-hit side effects for a free user (no-op for paid plans)."""
    if user_plan != PlanType.FREE:
        return
    spawn_background_task(_run(user_id, feature_key, origin))


async def _run(user_id: str, feature_key: str, origin: LimitHitOrigin) -> None:
    try:
        capture_event(user_id, "rate_limit_hit", {"feature": feature_key, "origin": origin.value})
        if origin == LimitHitOrigin.BACKGROUND:
            await send_workflows_paused_email(user_id)
        else:
            await send_limit_reached_email(user_id, feature_key)
    except Exception as e:
        log.warning(
            "Limit upsell side effects failed",
            user={"id": user_id},
            origin=origin.value,
            error=str(e),
            error_type=type(e).__name__,
        )
