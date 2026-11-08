"""The Inbox desk's own mail fetches, each email carrying its verdict's bucket: what the desk does with it.

The bucket decides what a desk run, or the mail subagent it spawns, does with every
email it fetched. A verdict the gate already asked for on arrival is reused, so JEV is
asked only about mail it never saw. An email JEV gives no usable bucket for reaches the
desk unbucketed, and the desk's prompt classifies it alone.
"""

import asyncio

from app.constants.desk_buckets import DeskBucket
from app.constants.trigger_gates import GateReason
from app.db.repositories.todos import todo_repository
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRefSource
from app.services.mail.email_verdict import email_verdict
from app.services.triggers.gmail_signals import fetched_message_payload, gmail_gate_view
from app.services.triggers.trigger_gate import jev_failure_reason
from shared.py.wide_events import log


async def _ask_bucket(user_id: str, view: GmailMessageView) -> DeskBucket | None:
    gate_view = gmail_gate_view(fetched_message_payload(view))
    if gate_view is None:
        return None
    try:
        # A conversation the gate saw on arrival is kept as reply; the sweep cannot tell one.
        verdict = await email_verdict(
            user_id, view.id, gate_view.as_event(), quiet=False, conversation=False
        )
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
    return verdict.bucket


async def desk_bucketed_views(
    user_id: str, todo_id: str, views: list[GmailMessageView]
) -> list[GmailMessageView]:
    """Return views in order, each carrying its bucket; unchanged when todo_id is not an Inbox desk."""
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None or todo.external_ref is None:
        return views
    if todo.external_ref.source is not ExternalRefSource.INBOX_DESK:
        return views
    return list(await asyncio.gather(*(_bucketed(user_id, view) for view in views)))


async def _bucketed(user_id: str, view: GmailMessageView) -> GmailMessageView:
    return view.model_copy(update={"bucket": await _ask_bucket(user_id, view)})
