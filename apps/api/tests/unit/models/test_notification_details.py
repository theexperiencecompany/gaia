"""A notification's details at the request boundary: every producer's shape validates, anything else is refused."""

from typing import get_args

from pydantic import TypeAdapter, ValidationError
import pytest

from app.constants.notifications import NotificationKind
from app.models.notification.details_models import NotificationDetails
from app.models.notification.notification_models import NotificationRequest

_CARD = {
    "briefing_id": "brief-1",
    "date": "2026-11-18",
    "kind": "daily",
    "headline": "Three things today",
    "edition": {"image_url": "https://cdn.test/e.png", "fold": None, "paper": None},
    "edition_name": "Swiss",
    "stamp_city_name": None,
    "needs_you_count": 1,
}

#: The details each producer sends, as they arrive from JSON or Mongo.
PRODUCER_DETAILS: dict[str, dict[str, object]] = {
    "brief edition (briefing/delivery)": {
        "kind": "briefing_daily",
        "brief_url": "https://heygaia.link/b",
        "card": _CARD,
    },
    "weekly recap (briefing/delivery)": {
        "kind": "briefing_weekly",
        "brief_url": "https://heygaia.link/b",
        "card": {**_CARD, "kind": "weekly", "edition_name": None},
    },
    "quiet note (briefing/delivery)": {"kind": "briefing_note"},
    "todo run result / health check": {"kind": "todo", "todo_id": "todo-1"},
    "tracked todo out of attempts": {"kind": "todo_failed", "todo_id": "todo-1", "retry_count": 3},
    "todo trigger fired": {
        "kind": "todo_trigger_fired",
        "todo_id": "todo-1",
        "subscription_id": "sub-1",
    },
    "dormant todo digest": {"kind": "dormant_todos", "todo_count": 2},
    "reminder": {"kind": "reminder", "reminder_id": "rem-1"},
    "workflow completed": {
        "kind": "workflow_completed",
        "workflow_id": "wf-1",
        "conversation_id": "conv-1",
    },
    "workflow failed (worker)": {
        "kind": "workflow_failed",
        "workflow_id": "wf-1",
        "error_type": "RuntimeError",
    },
    "workflow failed (executor)": {"kind": "workflow_failed", "workflow_id": "wf-1"},
    "workflow paused for integrations": {
        "kind": "workflow_paused",
        "workflow_id": "wf-1",
        "missing_integrations": ["gmail", "notion"],
    },
    "integration expired": {
        "kind": "integration_expired",
        "integration_id": "gmail",
        "paused_workflows": 1,
    },
    "system workflows provisioned": {
        "kind": "system_workflows_provisioned",
        "integration_display_name": "Gmail",
    },
    "memory seeded": {"kind": "memory_ready"},
    "gmail personalised": {"kind": "gmail_personalized"},
}

REFUSED_DETAILS: dict[str, dict[str, object]] = {
    "a kind no producer declares": {"kind": "todo_due", "todo_id": "todo-1"},
    "no kind at all (the old free-form bag)": {"todo_id": "todo-1"},
    "a key its kind does not carry": {"kind": "todo", "todo_id": "todo-1", "title": "x"},
    "a field of the wrong type": {"kind": "dormant_todos", "todo_count": "two"},
    "a required field missing": {"kind": "workflow_completed", "workflow_id": "wf-1"},
    "the old comma-joined integrations": {
        "kind": "workflow_paused",
        "workflow_id": "wf-1",
        "missing_integrations": "gmail,notion",
    },
    "an edition without its card": {"kind": "briefing_daily", "brief_url": "https://x"},
}


def _request(details: dict[str, object] | None) -> NotificationRequest:
    return NotificationRequest.model_validate(
        {
            "user_id": "user-1",
            "source": "background_job",
            "content": {"title": "t", "body": "b"},
            "details": details,
        }
    )


@pytest.mark.parametrize("details", PRODUCER_DETAILS.values(), ids=PRODUCER_DETAILS.keys())
def test_each_producers_details_validate_and_round_trip(details: dict[str, object]) -> None:
    request = _request(details)

    assert request.details is not None
    assert request.details.kind == details["kind"]
    assert _request(request.details.model_dump(mode="json")).details == request.details


def test_a_notification_may_carry_no_details() -> None:
    assert _request(None).details is None


@pytest.mark.parametrize("details", REFUSED_DETAILS.values(), ids=REFUSED_DETAILS.keys())
def test_details_outside_every_kind_are_refused_at_the_boundary(
    details: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="details"):
        _request(details)


def test_every_kind_has_exactly_one_details_model() -> None:
    (union, _discriminator) = get_args(NotificationDetails)
    kinds = [
        kind
        for model in get_args(union)
        for kind in get_args(model.model_fields["kind"].annotation)
    ]

    assert sorted(kinds) == sorted(NotificationKind)


def test_the_producer_table_covers_every_kind() -> None:
    adapter: TypeAdapter[NotificationDetails] = TypeAdapter(NotificationDetails)
    covered = {adapter.validate_python(details).kind for details in PRODUCER_DETAILS.values()}

    assert covered == set(NotificationKind)
