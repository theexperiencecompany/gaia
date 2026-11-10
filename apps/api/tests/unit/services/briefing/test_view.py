"""The archive's view of a brief: edition family and stamp city names, Needs you count.

The real explorer templates and stamp catalogue (cities.json) are read.
"""

from app.models.briefing_models import (
    BriefingItem,
    BriefingModel,
    BriefingPayload,
    BriefingSection,
)
from app.services.briefing.view import briefing_view


def _brief(
    *,
    template_family: str | None,
    stamp_city: str | None = None,
    sections: list[BriefingSection] | None = None,
) -> BriefingModel:
    return BriefingModel(
        id="brief_1",
        user_id="user-1",
        date="2026-10-21",
        payload=BriefingPayload(
            kicker="THE MORNING BRIEF",
            date="2026-10-21",
            headline="Three things wait on you",
            lede="A short day.",
            mood="clear",
            caption="Onward.",
            template_family=template_family,
            stamp_city=stamp_city,
            sections=sections or [],
        ),
    )


def test_an_air_mail_brief_names_its_family_and_stamp_city() -> None:
    view = briefing_view(_brief(template_family="postal", stamp_city="bogota"))

    assert (view.edition_name, view.stamp_city_name) == ("Air Mail", "Bogotá")
    assert view.id == "brief_1"


def test_a_legacy_brief_has_no_edition_names() -> None:
    view = briefing_view(_brief(template_family=None))

    assert (view.edition_name, view.stamp_city_name) == (None, None)


def test_needs_you_counts_every_item_waiting_on_the_reader_in_any_section() -> None:
    """The lead can be a needs-you item too; the editions list it with the other decisions."""
    lead = BriefingSection(
        numeral="I", title="First up", items=[BriefingItem(text="Reply to Priya", kind="you")]
    )
    needs_you = BriefingSection(
        numeral="II",
        title="Needs you",
        items=[
            BriefingItem(text="Approve the MSA", count=3, kind="you"),
            BriefingItem(text="Retry the export", kind="failed"),
        ],
    )
    gaias_work = BriefingSection(
        numeral="III",
        title="GAIA's work",
        items=[BriefingItem(text="Drafted the memo", kind="lookback"), BriefingItem(text="FYI")],
    )

    view = briefing_view(
        _brief(template_family="flightplan", sections=[lead, needs_you, gaias_work])
    )

    assert view.needs_you_count == 3
    assert view.edition_name == "The Blueprint"
