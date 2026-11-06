"""The Inbox desk's own mail fetches pass the gate its Gmail watch passes: one judge of what needs the user."""

from app.constants.trigger_gates import GMAIL_MESSAGE_TRIGGERS, GateOwner
from app.db.repositories.todos import todo_repository
from app.models.composio_schemas.gmail import GmailMessageView
from app.models.todo_models import ExternalRefSource
from app.services.triggers.gmail_signals import fetched_message_payload
from app.services.triggers.trigger_gate import (
    GatedJob,
    GateSkip,
    automation_text,
    decide_fetched_mail,
)


async def desk_gated_views(
    user_id: str, todo_id: str, views: list[GmailMessageView]
) -> list[GmailMessageView]:
    """Return the views the desk's Gmail gate lets through; all of them when todo_id is no gated desk."""
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None or todo.external_ref is None:
        return views
    if todo.external_ref.source is not ExternalRefSource.INBOX_DESK:
        return views
    watch = next(
        (
            subscription
            for subscription in todo.trigger_subscriptions
            if subscription.trigger_name in GMAIL_MESSAGE_TRIGGERS and subscription.gate is not None
        ),
        None,
    )
    if watch is None:
        return views
    verdicts = await decide_fetched_mail(
        watch.gate,
        GatedJob(
            owner=GateOwner.TODO,
            id=watch.id,
            user_id=user_id,
            automation=automation_text(todo.title, todo.description),
        ),
        [fetched_message_payload(view) for view in views],
    )
    return [
        view
        for view, verdict in zip(views, verdicts, strict=True)
        if not isinstance(verdict, GateSkip)
    ]
