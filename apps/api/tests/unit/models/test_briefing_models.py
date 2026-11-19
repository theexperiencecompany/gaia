"""The brief item contract: a short title, one detail line, and exactly one of action or outcome."""

from pydantic import ValidationError
import pytest

from app.constants.briefing import (
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BriefAction,
    BriefOutcome,
)
from app.models.briefing_models import BriefingItem


def _ask(**fields: object) -> BriefingItem:
    return BriefingItem.model_validate(
        {"text": "Acme invoice", "action": BriefAction.APPROVE, **fields}
    )


def _report(text: str = "Investor update") -> BriefingItem:
    return BriefingItem(text=text, outcome=BriefOutcome.FINISHED)


class TestTheItem:
    def test_a_title_and_detail_at_their_caps_are_kept(self) -> None:
        item = _ask(text="t" * BRIEF_ITEM_TITLE_MAX_CHARS, detail="d" * BRIEF_ITEM_DETAIL_MAX_CHARS)

        assert (len(item.text), len(item.detail or "")) == (
            BRIEF_ITEM_TITLE_MAX_CHARS,
            BRIEF_ITEM_DETAIL_MAX_CHARS,
        )

    @pytest.mark.parametrize(
        "fields",
        [
            {"text": "t" * (BRIEF_ITEM_TITLE_MAX_CHARS + 1)},
            {"text": ""},
            {"detail": "d" * (BRIEF_ITEM_DETAIL_MAX_CHARS + 1)},
            {"detail": ""},
        ],
    )
    def test_a_title_or_detail_past_its_cap_is_refused(self, fields: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            _ask(**fields)

    @pytest.mark.parametrize(
        "fields",
        [{}, {"action": BriefAction.READ, "outcome": BriefOutcome.LANDED}],
        ids=["neither", "both"],
    )
    def test_an_item_needs_exactly_one_of_action_or_outcome(
        self, fields: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError, match="exactly one of action or outcome"):
            BriefingItem.model_validate({"text": "PR #412", **fields})
