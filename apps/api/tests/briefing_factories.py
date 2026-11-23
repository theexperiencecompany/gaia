"""Factories for the briefing stack's documents, apart from tests.factories so the shared harness imports only base code."""

from typing import Any

from app.constants.briefing import DAILY_KICKER, BriefAction, BriefOutcome, EditionFamily
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import BriefingMood, BriefingPayload

# How a brief item of each kind reads when a test does not say: asks act, the rest report.
_BRIEF_ITEM_READS_AS: dict[ItemState, dict[str, BriefAction | BriefOutcome]] = {
    ItemState.YOU: {"action": BriefAction.APPROVE},
    ItemState.FAILED: {"action": BriefAction.RETRY},
    ItemState.GAIA: {"outcome": BriefOutcome.STARTED},
    ItemState.LOOKBACK: {"outcome": BriefOutcome.FINISHED},
    ItemState.NOTE: {"outcome": BriefOutcome.CHANGED},
}


def make_brief_item(text: str, kind: str = ItemState.NOTE, **fields: Any) -> dict[str, Any]:
    """Build a BriefingItem's fields; without an action or outcome it reads as its kind does."""
    reads_as = (
        {} if {"action", "outcome"} & fields.keys() else _BRIEF_ITEM_READS_AS[ItemState(kind)]
    )
    return {"text": text, "kind": kind, **reads_as, **fields}


def make_briefing_payload(**overrides: Any) -> BriefingPayload:
    """Build a daily brief's payload, drawn as a Swiss edition; overrides are BriefingPayload fields."""
    return BriefingPayload.model_validate(
        {
            "kicker": DAILY_KICKER,
            "template_family": EditionFamily.SWISS,
            "date": "2026-10-14",
            "headline": "Your morning, sorted",
            "lede": "Everything else is moving.",
            "mood": BriefingMood.CLEAR,
            "caption": "Onward.",
            **overrides,
        }
    )
