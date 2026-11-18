"""What each edition family draws, and the edition draw that follows the composition."""

from collections import Counter
from itertools import pairwise
from typing import Any
from unittest.mock import patch

import pytest

from app.constants.briefing import EditionChoice
from app.models.brief_composition_models import BriefBlock, ChartKind
from app.models.briefing_models import BriefingPayload
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing.edition_draws import daily_family_weights, draw_edition
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS, EXPLORER_RENDERER
from app.services.briefing.editions.capabilities import (
    edition_capabilities,
    families_drawing,
    split_drawable,
)

_SERIES = {
    "id": "mail",
    "label": "Emails received",
    "unit": "emails",
    "source": "gmail",
    "app": "Gmail",
    "shape": "time_series",
    "points": [{"x": f"2026-11-0{d}", "y": d} for d in range(1, 8)],
}
_GOAL = {"id": "g", "statement": "Hire eight", "origin": "memory", "done": 5, "open": 3}
_QUOTE = {
    "id": "q",
    "text": "Hold the cap.",
    "author": "Dana",
    "source": "gmail",
    "app": "Gmail",
    "item_id": 1,
}


def _blocks(*raw: dict[str, Any]) -> list[BriefBlock]:
    payload = BriefingPayload.model_validate(
        {
            "kicker": "",
            "date": "2026-11-10",
            "headline": "",
            "lede": "",
            "mood": "clear",
            "caption": "",
            "template_family": "swiss",
            "blocks": list(raw),
        }
    )
    return payload.blocks


def _chart(kind: ChartKind) -> dict[str, Any]:
    return {
        "kind": "chart",
        "chart": kind.value,
        "title": "t",
        "takeaway": "k",
        "series": [_SERIES],
    }


_NOTE = {"kind": "note", "text": "Mornings are tight."}
_PROGRESS = {"kind": "progress", "goal": _GOAL}
_LEAD = {"kind": "lead", "section": 0}


@pytest.mark.unit
class TestCapabilities:
    @pytest.mark.parametrize("family", sorted(EXPLORER_RENDERER))
    def test_every_family_draws_items_and_notes(self, family: str) -> None:
        caps = edition_capabilities(family)

        assert {"items", "note"} <= caps.blocks

    @pytest.mark.parametrize(
        ("family", "leaves_out"),
        [
            ("menu", {"chart:bar", "chart:line", "chart:spark", "chart:stacked_bar", "progress"}),
            ("postal", {"chart:bar", "chart:line", "chart:spark", "chart:stacked_bar"}),
            ("memo", {"chart:line", "chart:spark"}),
            ("weekly", {"lead", "quote"}),
            ("swiss", set()),
        ],
    )
    def test_a_family_leaves_out_what_the_gallery_says_it_cannot_draw(
        self, family: str, leaves_out: set[str]
    ) -> None:
        candidates = {
            **{f"chart:{k.value}": _chart(k) for k in ChartKind},
            "progress": _PROGRESS,
            "lead": _LEAD,
            "quote": {"kind": "quote", "quote": _QUOTE},
            "note": _NOTE,
        }
        caps = edition_capabilities(family)

        undrawn = {name for name, raw in candidates.items() if not caps.draws(_blocks(raw)[0])}

        assert undrawn == leaves_out

    def test_only_families_drawing_every_block_fit(self) -> None:
        fits = families_drawing(DAILY_FAMILY_WEIGHTS, _blocks(_chart(ChartKind.LINE), _PROGRESS))

        assert "menu" not in fits
        assert "memo" not in fits
        assert "postal" not in fits
        assert fits == set(DAILY_FAMILY_WEIGHTS) - {"menu", "memo", "postal"}

    def test_split_keeps_the_reading_order_of_both_halves(self) -> None:
        blocks = _blocks(_NOTE, _chart(ChartKind.BAR), _PROGRESS, _chart(ChartKind.LINE))

        drawn, undrawn = split_drawable("menu", blocks)

        assert [b.kind for b in drawn] == ["note"]
        assert [getattr(b, "chart", b.kind) for b in undrawn] == [
            ChartKind.BAR,
            "progress",
            ChartKind.LINE,
        ]


def _user(order: list[str], index: int = 0) -> UserDocument:
    return UserDocument(
        id="u1",
        email="a@b.c",
        briefing_shuffle_bags={"edition_family": ShuffleBag(order=order, index=index)},
    )


def _pass_opening_with(first: str) -> list[str]:
    pool = [f for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n)]
    pool.remove(first)
    return [first, *pool]


@pytest.mark.unit
class TestDrawEdition:
    def test_the_bags_next_family_draws_when_it_can_draw_everything(self) -> None:
        draw = draw_edition(_user(_pass_opening_with("menu")), _blocks(_NOTE), None)

        assert draw.family == "menu"
        assert draw.undrawn == []

    def test_a_family_that_cannot_draw_a_block_keeps_its_turn_for_a_later_day(self) -> None:
        order = _pass_opening_with("menu")

        draw = draw_edition(_user(order), _blocks(_NOTE, _PROGRESS), None)

        assert draw.family == order[1]
        assert draw.draws[0].next_state.order[1] == "menu"
        assert [b.kind for b in draw.drawn] == ["note", "progress"]
        assert draw.undrawn == []

    def test_with_no_fitting_family_on_the_next_one_draws_and_the_rest_go_to_the_page(
        self,
    ) -> None:
        user = _user_choosing(_only_on("menu", "postal"))

        draw = draw_edition(user, _blocks(_NOTE, _chart(ChartKind.LINE)), None)

        assert draw.family in {"menu", "postal"}
        assert [b.kind for b in draw.drawn] == ["note"]
        assert [b.kind for b in draw.undrawn] == ["chart"]


def _user_choosing(choices: dict[str, EditionChoice]) -> UserDocument:
    return UserDocument(id="u1", email="a@b.c", briefing_editions=choices)


def _only_on(*families: str) -> dict[str, EditionChoice]:
    return {f: EditionChoice.OFF for f in DAILY_FAMILY_WEIGHTS if f not in families}


def _draw_days(user: UserDocument, days: int, blocks: list[BriefBlock]) -> list[str]:
    picks: list[str] = []
    for _ in range(days):
        family = draw_edition(user, blocks, None).draws[0]
        picks.append(family.member)
        user = user.model_copy(update={"briefing_shuffle_bags": {family.bag: family.next_state}})
    return picks


@pytest.mark.unit
class TestEditionChoices:
    def test_favourites_draw_twice_as_often_and_an_edition_turned_off_never_draws(
        self,
    ) -> None:
        user = _user_choosing(
            {
                "menu": EditionChoice.OFF,
                "swiss": EditionChoice.FAVOURITE,
                "postal": EditionChoice.FAVOURITE,
            }
        )
        # menu out, swiss 1 -> 2, postal 2 -> 4
        per_pass = sum(DAILY_FAMILY_WEIGHTS.values()) - 1 + 1 + 2

        picks = Counter(_draw_days(user, 3 * per_pass, _blocks(_NOTE)))

        assert picks["menu"] == 0
        assert picks["memo"] == 3
        assert picks["swiss"] == 6
        assert picks["postal"] == 12

    def test_a_single_edition_left_on_is_drawn_every_day(self) -> None:
        picks = _draw_days(_user_choosing(_only_on("swiss")), 5, _blocks(_NOTE))

        assert picks == ["swiss"] * 5

    def test_two_editions_left_on_take_turns_every_day(self) -> None:
        picks = _draw_days(_user_choosing(_only_on("swiss", "memo")), 8, _blocks(_NOTE))

        assert set(picks) == {"swiss", "memo"}
        assert all(a != b for a, b in pairwise(picks))

    def test_when_every_edition_left_on_was_retired_every_daily_family_draws_loudly(
        self,
    ) -> None:
        choices = _only_on("retired") | {"retired": EditionChoice.FAVOURITE}

        with patch("app.services.briefing.edition_draws.log") as log:
            weights = daily_family_weights(choices)

        assert weights == DAILY_FAMILY_WEIGHTS
        log.warning.assert_called_once_with("briefing.editions_all_retired", kept=sorted(choices))
