"""The Inbox desk's own mail fetches, bucketed by one JEV choice per email: what the desk does with each.

The bucket decides what a desk run, or the mail subagent it spawns, does with every
email it fetched. An email JEV gives no usable bucket for reaches the desk unbucketed,
and the desk's prompt classifies it alone.
"""

import asyncio
from collections.abc import Mapping

from app.constants.desk_buckets import (
    DESK_BUCKET_CRITERIA,
    DESK_BUCKET_INSTRUCTIONS,
    DESK_BUCKET_JEV_LIMIT,
    DESK_BUCKET_JEV_LIMIT_KEY,
    DESK_BUCKET_JEV_TIMEOUT_SECONDS,
    DESK_BUCKET_JUNK_PROBABILITY,
    DESK_BUCKET_QUESTION_KEY,
    DeskBucket,
)
from app.constants.trigger_gates import (
    SYSTEM_GATE_PRESETS,
    GateReason,
    SystemGatePreset,
)
from app.db.repositories.todos import todo_repository
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.jev_models import JevDecisionsResponse
from app.models.todo_models import ExternalRefSource
from app.services.hil.jev_client import post_decisions
from app.services.triggers.gmail_signals import fetched_message_payload, gmail_gate_view
from app.services.triggers.trigger_gate import jev_failure_reason
from app.utils.concurrency import loop_bound_semaphore
from shared.py.wide_events import log

_DESK_AUTOMATION = SYSTEM_GATE_PRESETS[SystemGatePreset.INBOX_DESK].automation
_BUCKET_LABELS = frozenset(DeskBucket)


def bucket_request(
    event: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Return the Decisions state and bucket question for one email; pure, so the eval sends the same bytes."""
    state: dict[str, object] = {"event": dict(event), "automation": _DESK_AUTOMATION}
    questions: dict[str, dict[str, object]] = {
        DESK_BUCKET_QUESTION_KEY: {
            "type": "choice",
            "instructions": DESK_BUCKET_INSTRUCTIONS,
            "criteria": {bucket.value: text for bucket, text in DESK_BUCKET_CRITERIA.items()},
        }
    }
    return state, questions


def read_bucket(body: JevDecisionsResponse) -> DeskBucket | None:
    """Return JEV's bucket, None for a junk under the line; raise ValueError for a choice never offered."""
    answer = body.choice(DESK_BUCKET_QUESTION_KEY, _BUCKET_LABELS, label="bucket ")
    bucket = DeskBucket(answer.choice)
    p_junk = (answer.probabilities or {}).get(DeskBucket.JUNK)
    if bucket is DeskBucket.JUNK and (p_junk is None or p_junk < DESK_BUCKET_JUNK_PROBABILITY):
        return None
    return bucket


async def _ask_bucket(view: GmailMessageView) -> DeskBucket | None:
    gate_view = gmail_gate_view(fetched_message_payload(view))
    if gate_view is None:
        return None
    state, questions = bucket_request(gate_view.as_event())
    # pragma: no mutate start — any key names one process-wide semaphore.
    limit = loop_bound_semaphore(DESK_BUCKET_JEV_LIMIT_KEY, DESK_BUCKET_JEV_LIMIT)
    # pragma: no mutate end
    try:
        async with limit, asyncio.timeout(DESK_BUCKET_JEV_TIMEOUT_SECONDS):
            body = await post_decisions(state, questions)
        return read_bucket(body)
    except Exception as e:
        # The one degradation a bucket has: the desk's own prompt judges the email.
        reason = jev_failure_reason(e)
        if reason is not GateReason.JEV_UNCONFIGURED:
            log.warning(
                "desk_bucket.jev_failed",
                reason=reason.value,
                error=str(e)[:300],
                error_type=type(e).__name__,
            )
        return None


async def desk_bucketed_views(
    user_id: str, todo_id: str, views: list[GmailMessageView]
) -> list[GmailMessageView]:
    """Return views in order, each carrying its bucket; unchanged when todo_id is not an Inbox desk."""
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None or todo.external_ref is None:
        return views
    if todo.external_ref.source is not ExternalRefSource.INBOX_DESK:
        return views
    return list(await asyncio.gather(*(_bucketed(view) for view in views)))


async def _bucketed(view: GmailMessageView) -> GmailMessageView:
    return view.model_copy(update={"bucket": await _ask_bucket(view)})
