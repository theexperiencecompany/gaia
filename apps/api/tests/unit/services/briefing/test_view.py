"""The archive's view of a brief: edition family and stamp city names, Needs you count.

The real explorer templates and stamp catalogue (cities.json) are read.
"""

from app.config.settings import settings
from app.constants.briefing import BriefAction, BriefOutcome
from app.models.brief_document_models import BriefingModel, EditionRender
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
)
from app.services.briefing.view import briefing_view, public_view


def _brief(
    *,
    template_family: str,
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
            mood=BriefingMood.CLEAR,
            caption="Onward.",
            template_family=template_family,
            stamp_city=stamp_city,
            sections=sections or [],
        ),
    )


async def test_an_air_mail_brief_names_its_family_and_stamp_city() -> None:
    view = await briefing_view(_brief(template_family="postal", stamp_city="bogota"))

    assert (view.edition_name, view.stamp_city_name) == ("Air Mail", "Bogotá")
    assert view.id == "brief_1"


async def test_needs_you_counts_every_item_waiting_on_the_reader_in_any_section() -> None:
    """The lead can be a needs-you item too; the editions list it with the other decisions."""
    lead = BriefingSection(
        numeral="I",
        title="First up",
        items=[BriefingItem(text="Priya", action=BriefAction.REPLY, kind="you")],
    )
    needs_you = BriefingSection(
        numeral="II",
        title="Needs you",
        items=[
            BriefingItem(text="The MSA", action=BriefAction.APPROVE, count=3, kind="you"),
            BriefingItem(text="The export", action=BriefAction.RETRY, kind="failed"),
        ],
    )
    gaias_work = BriefingSection(
        numeral="III",
        title="GAIA's work",
        items=[
            BriefingItem(text="The memo", outcome=BriefOutcome.DRAFTED, kind="lookback"),
            BriefingItem(text="FYI", outcome=BriefOutcome.CHANGED),
        ],
    )

    view = await briefing_view(
        _brief(template_family="flightplan", sections=[lead, needs_you, gaias_work])
    )

    assert view.needs_you_count == 3


async def test_every_daily_edition_is_named_as_its_settings_list_it() -> None:
    view = await briefing_view(_brief(template_family="flightplan"))

    assert (view.edition_name, view.stamp_city_name) == ("The Blueprint", None)


async def test_the_weekly_recap_and_a_quiet_note_carry_no_edition_name() -> None:
    assert (await briefing_view(_brief(template_family="weekly"))).edition_name is None
    assert (await briefing_view(_brief(template_family=None))).edition_name is None


async def test_an_edition_is_shown_by_its_signed_url_and_a_quiet_note_by_none() -> None:
    stored = _brief(template_family="memo").model_copy(
        update={"edition": EditionRender(key="k1", fold=0.3, paper=None)}
    )

    view = await briefing_view(stored)

    assert view.edition is not None
    assert view.edition.image_url.startswith(f"{settings.HOST}/api/v1/briefings/editions/k1/png?t=")
    assert (view.edition.fold, view.edition.paper) == (0.3, None)
    assert (await briefing_view(_brief(template_family=None))).edition is None


async def test_a_public_viewer_sees_the_front_page_never_an_item_or_the_calendar() -> None:
    owned = _brief(
        template_family="memo",
        sections=[
            BriefingSection(
                numeral="I",
                title="Waiting on you",
                items=[BriefingItem(text="Reply to Priya", action=BriefAction.REPLY, kind="you")],
            )
        ],
    )
    calendar = [BriefingEvent(date="2026-10-21", start="11:00", title="Therapy")]
    owned = owned.model_copy(
        update={
            "payload": owned.payload.model_copy(update={"calendar": calendar}),
            "edition": EditionRender(key="k1"),
        }
    )

    seen = (await public_view(owned)).model_dump_json()

    assert "Three things wait on you" in seen
    assert "k1/png?t=" in seen
    for private in ("Reply to Priya", "Waiting on you", "Therapy", "user-1", "brief_1"):
        assert private not in seen
