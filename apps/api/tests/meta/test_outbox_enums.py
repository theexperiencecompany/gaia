"""The outbox vocabularies are closed: adding a member is a reviewed change, so this lists them all.

The analytics event names the same values as literals (the catalog cannot import the app), so the
two are pinned together here.
"""

from enum import StrEnum
from typing import get_args

from app.constants.outbox_attention import HoldReason
from app.models.ownership_models import DeliveryTiming
from app.services.outbox.models import (
    ComposeMode,
    Disposition,
    DropReason,
    Initiative,
    ItemFailure,
    ItemState,
    MessageState,
    NoticeOutcome,
    ProducerKind,
    SubjectKind,
    SubjectMerge,
    UrgencyClass,
)
from app.services.outbox.prerendered import PrerenderedKind
from shared.py.analytics.catalog.delivery import DeliveryItemHeld, DeliveryMessageSent


def _values(enum: type[StrEnum]) -> set[str]:
    return {member.value for member in enum}


def test_the_closed_vocabularies_are_exactly_these() -> None:
    assert _values(SubjectKind) == {
        "ask",
        "workflow_run",
        "todo_run",
        "reminder",
        "browser_job",
        "account",
        "approval",
    }
    assert _values(SubjectMerge) == {"replace", "accumulate"}
    assert _values(ProducerKind) == {
        "executor",
        "workflow",
        "todo",
        "reminder",
        "browser",
        "artifact",
        "account",
        "approval",
    }
    assert _values(Initiative) == {"asked", "user_scheduled", "self_initiated"}
    assert _values(DeliveryTiming) == {"the_moment", "at_time", "when_done"}
    assert _values(NoticeOutcome) == {"info", "needs_you", "failed", "progress"}
    assert _values(ComposeMode) == {"answer", "unsolicited", "interrupt"}
    assert _values(ItemState) == {
        "received",
        "queued",
        "held",
        "composing",
        "sending",
        "sent",
        "dropped",
        "superseded",
        "failed",
    }
    assert _values(DropReason) == {
        "nothing_new",
        "cancelled",
        "compose_skipped",
        "user_muted",
        "not_watching",
        "expired",
        "already_known",
        "moot",
        "superseded",
        "duplicate",
        "unwanted",
        "repeat_backoff",
        "leak_unresolved",
    }
    assert _values(ItemFailure) == {
        "no_destination",
        "record_failed",
        "transport_skipped",
        "transport_failed",
    }
    assert _values(MessageState) == {"sending", "sent", "failed"}
    assert _values(Disposition) == {"include", "skip"}
    assert _values(PrerenderedKind) == {
        "compose_degraded",
        "account_linked",
        "first_contact",
        "generic_preview",
    }


def test_urgency_classes_are_ordered_from_background_to_interrupt() -> None:
    assert [c.name for c in sorted(UrgencyClass)] == [
        "BACKGROUND",
        "ROUTINE",
        "TIMELY",
        "INTERRUPT",
    ]


def _literal(field: str) -> set[str]:
    return set(get_args(DeliveryMessageSent.model_fields[field].annotation))


def test_the_analytics_event_names_the_same_values_as_the_enums() -> None:
    assert _literal("producer") == _values(ProducerKind)
    assert _literal("subject_kind") == _values(SubjectKind)
    assert _literal("mode") == _values(ComposeMode)
    assert _literal("max_class") == {c.name.lower() for c in UrgencyClass}


def test_the_held_event_names_the_same_values_as_the_hold_reasons() -> None:
    held = DeliveryItemHeld.model_fields
    assert set(get_args(held["reason"].annotation)) == _values(HoldReason)
    assert set(get_args(held["max_class"].annotation)) == {c.name.lower() for c in UrgencyClass}
