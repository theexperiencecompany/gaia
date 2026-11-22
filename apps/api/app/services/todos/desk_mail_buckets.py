"""The Inbox desk's own mail fetches, each email carrying its verdict's bucket: what the desk does with it.

The bucket decides what a desk run, or the mail subagent it spawns, does with every
email it fetched. A verdict the gate already asked for on arrival is reused, so JEV is
asked only about mail it never saw. An email JEV gives no usable bucket for reaches the
desk unbucketed, and the desk's prompt classifies it alone.
"""

import asyncio

from app.constants.desk_buckets import DeskBucket
from app.constants.hil import JevFailure
from app.db.repositories.todos import todo_repository
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRefSource
from app.services.hil.jev_client import jev_failure
from app.services.mail.email_verdict import ThreadFacts, email_verdict
from app.services.mail.thread_participation import user_wrote_in_thread
from app.services.triggers.gmail_signals import (
    GmailGateView,
    fetched_message_payload,
    gmail_gate_view,
)
from shared.py.wide_events import log


async def _ask_bucket(user_id: str, view: GmailMessageView) -> DeskBucket | None:
    gate_view = gmail_gate_view(fetched_message_payload(view))
    if gate_view is None:
        return None
    try:
        verdict = await email_verdict(
            user_id,
            view.id,
            gate_view.as_email(),
            thread=await _thread_facts(user_id, view, gate_view),
        )
    except Exception as e:
        # The one degradation a bucket has: the desk's own prompt judges the email.
        reason = jev_failure(e)
        if reason is not JevFailure.UNCONFIGURED:
            log.warning(
                "desk_bucket.jev_failed",
                reason=reason.value,
                error=str(e)[:300],
                error_type=type(e).__name__,
            )
        return None
    return verdict.bucket


async def _thread_facts(
    user_id: str, view: GmailMessageView, gate_view: GmailGateView
) -> ThreadFacts:
    """Read the thread as the arrival gate does, on the account the desk's fetch is scoped to.

    A message the signals cannot place counts as one the user wrote in; a failed read raises.
    """
    placed = gate_view.continues_thread
    wrote = placed is None or (
        placed
        and await user_wrote_in_thread(user_id, view.thread_id, message_id=view.id, account_id=None)
    )
    return ThreadFacts(user_wrote_in_thread=wrote, latest_from_other=gate_view.latest_from_other)


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
