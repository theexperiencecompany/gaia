"""The brief item contract: a short title, one detail line, and exactly one of action or outcome."""

from pydantic import ValidationError
import pytest

from app.constants.briefing import (
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BriefAction,
    BriefOutcome,
    SectionKey,
)
from app.models.briefing_models import BriefingItem, BriefingSection


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


class TestTheSection:
    @pytest.mark.parametrize("key", [SectionKey.LEAD, SectionKey.NEEDS_YOU])
    def test_a_section_that_asks_refuses_a_report(self, key: SectionKey) -> None:
        with pytest.raises(ValidationError, match="items need an action"):
            BriefingSection(numeral="I", title="Needs you", key=key, items=[_ask(), _report()])

    @pytest.mark.parametrize("key", [SectionKey.UPDATES, SectionKey.GAIA_DID])
    def test_a_section_that_reports_refuses_an_ask(self, key: SectionKey) -> None:
        with pytest.raises(ValidationError, match="items need an outcome"):
            BriefingSection(numeral="II", title="Updates", key=key, items=[_report(), _ask()])

    def test_a_section_counts_what_its_cap_left_out(self) -> None:
        section = BriefingSection(
            numeral="I", title="Needs you", key=SectionKey.NEEDS_YOU, items=[_ask()], more=3
        )

        assert section.more == 3
        with pytest.raises(ValidationError):
            BriefingSection(numeral="I", title="Needs you", more=-1)
