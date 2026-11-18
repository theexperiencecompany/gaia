"""The composed sample briefs: what each family is handed, and the attribution their items carry."""

from app.constants.briefing import BriefAction, BriefOutcome, EditionFamily
from app.models.brief_composition_models import ChartBlock
from app.services.dev_brief_compositions import COMPOSITIONS, composed_payload

_DRAWS_EVERYTHING = EditionFamily.SWISS


def test_a_family_without_charts_gets_the_chart_as_undrawn_and_draws_the_rest_in_order() -> None:
    payload = composed_payload("busy", EditionFamily.POSTAL, "stamp-art")

    assert [block.kind for block in payload.blocks] == ["lead", "items", "items", "quote", "note"]
    assert [block.kind for block in payload.undrawn] == ["chart"]
    assert payload.template_family == EditionFamily.POSTAL
    assert payload.artwork_id == "stamp-art"


def test_a_family_that_draws_everything_leaves_nothing_undrawn() -> None:
    for composition in COMPOSITIONS:
        payload = composed_payload(composition, _DRAWS_EVERYTHING, None)

        assert payload.undrawn == []
        assert len(payload.blocks) == len(COMPOSITIONS[composition]["blocks"])


def test_asks_and_done_items_carry_their_app_and_detail() -> None:
    payload = composed_payload("busy", _DRAWS_EVERYTHING, None)
    ask = payload.sections[0].items[0]
    done = payload.sections[2].items[0]

    assert (ask.kind, ask.action, ask.source, ask.app) == (
        "you",
        BriefAction.APPROVE,
        "gmail",
        "Gmail",
    )
    assert ask.detail == "Due Thu 17:00. Last year's terms capped rises at 10%."
    assert (done.kind, done.outcome, done.source, done.app) == (
        "lookback",
        BriefOutcome.APPROVED,
        "github",
        "GitHub",
    )
    assert done.detail == "Sam K. and Ines M. on GitHub"


def test_a_chart_series_is_named_by_its_source_with_one_point_per_day() -> None:
    payload = composed_payload("spike", _DRAWS_EVERYTHING, None)
    chart = next(block for block in payload.blocks if isinstance(block, ChartBlock))
    series = chart.series[0]

    assert (series.id, series.label, series.unit, series.source, series.app, series.shape) == (
        "mail_received",
        "Emails received",
        "emails",
        "gmail",
        "Gmail",
        "time_series",
    )
    assert [point.y for point in series.points] == [18, 22, 19, 24, 20, 23, 61]
    assert [point.x for point in series.points][-1] == "2026-11-10"
