"""A brief's card (edition family and stamp city names, Needs you count), its owner's view and what its edition left out.

The real explorer templates and stamp catalogue (cities.json) are read.
"""

from app.config.settings import settings
from app.constants.briefing import EDITION_ROWS_SHOWN, BriefAction, BriefOutcome, EditionFamily
from app.models.brief_composition_models import BriefBlock, SectionBlock
from app.models.brief_document_models import BriefingModel, EditionRender
from app.models.brief_item_models import ItemState
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
    BriefPoolItem,
)
from app.services.briefing.view import briefing_card, briefing_view, public_view


def _brief(
    *,
    template_family: EditionFamily | None,
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
    card = await briefing_card(_brief(template_family=EditionFamily.POSTAL, stamp_city="bogota"))

    assert (card.edition_name, card.stamp_city_name) == ("Air Mail", "Bogotá")
    assert (card.briefing_id, card.headline) == ("brief_1", "Three things wait on you")


async def test_needs_you_counts_every_item_waiting_on_the_reader_in_any_section() -> None:
    """The lead can be a needs-you item too; the editions list it with the other decisions."""
    lead = BriefingSection(
        numeral="I",
        title="First up",
        items=[BriefingItem(text="Priya", action=BriefAction.REPLY, kind=ItemState.YOU)],
    )
    needs_you = BriefingSection(
        numeral="II",
        title="Needs you",
        items=[
            BriefingItem(text="The MSA", action=BriefAction.APPROVE, count=3, kind=ItemState.YOU),
            BriefingItem(text="The export", action=BriefAction.RETRY, kind=ItemState.FAILED),
        ],
    )
    gaias_work = BriefingSection(
        numeral="III",
        title="GAIA's work",
        items=[
            BriefingItem(text="The memo", outcome=BriefOutcome.DRAFTED, kind=ItemState.LOOKBACK),
            BriefingItem(text="FYI", outcome=BriefOutcome.CHANGED),
        ],
    )

    card = await briefing_card(
        _brief(template_family=EditionFamily.FLIGHTPLAN, sections=[lead, needs_you, gaias_work])
    )

    assert card.needs_you_count == 3


async def test_every_daily_edition_is_named_as_its_settings_list_it() -> None:
    card = await briefing_card(_brief(template_family=EditionFamily.FLIGHTPLAN))

    assert (card.edition_name, card.stamp_city_name) == ("The Blueprint", None)


async def test_the_weekly_recap_and_a_quiet_note_carry_no_edition_name() -> None:
    assert (await briefing_card(_brief(template_family=EditionFamily.WEEKLY))).edition_name is None
    assert (await briefing_card(_brief(template_family=None))).edition_name is None


async def test_an_edition_is_shown_by_its_signed_url_and_a_quiet_note_by_none() -> None:
    stored = _brief(template_family=EditionFamily.MEMO).model_copy(
        update={"edition": EditionRender(key="k1", fold=0.3, paper=None)}
    )

    card = await briefing_card(stored)

    assert card.edition is not None
    assert card.edition.image_url.startswith(f"{settings.HOST}/api/v1/briefings/editions/k1/png?t=")
    assert (card.edition.fold, card.edition.paper) == (0.3, None)
    assert (await briefing_card(_brief(template_family=None))).edition is None


async def test_the_owners_view_carries_the_briefs_card() -> None:
    brief = _brief(template_family=EditionFamily.POSTAL, stamp_city="bogota")

    view = await briefing_view(brief)

    assert view.card == await briefing_card(brief)
    assert view.payload == brief.payload


def _items(section: int, count: int) -> list[BriefingItem]:
    return [
        BriefingItem(text=f"{section}.{n}", outcome=BriefOutcome.FINISHED) for n in range(count)
    ]


def _with_blocks(
    brief: BriefingModel, *, blocks: list[BriefBlock], undrawn: list[BriefBlock]
) -> BriefingModel:
    return brief.model_copy(
        update={"payload": brief.payload.model_copy(update={"blocks": blocks, "undrawn": undrawn})}
    )


async def test_the_view_lists_the_undrawn_sections_then_the_rows_past_the_editions_own() -> None:
    sections = [
        BriefingSection(numeral="I", title="Lead", items=_items(0, 1)),
        BriefingSection(numeral="II", title="Asks", items=_items(1, EDITION_ROWS_SHOWN + 2)),
        BriefingSection(numeral="III", title="Done", items=_items(2, EDITION_ROWS_SHOWN)),
        BriefingSection(numeral="IV", title="Undrawn", items=_items(3, 2)),
    ]
    brief = _with_blocks(
        _brief(template_family=EditionFamily.MENU, sections=sections),
        blocks=[
            SectionBlock(kind="lead", section=0),
            SectionBlock(kind="items", section=1),
            SectionBlock(kind="items", section=2),
        ],
        undrawn=[SectionBlock(kind="items", section=3)],
    )

    left_out = (await briefing_view(brief)).left_out

    assert [item.text for item in left_out.items] == ["3.0", "3.1", "1.3", "1.4"]


async def test_the_view_lists_the_days_events_past_the_editions_calendar_rows() -> None:
    events = [
        BriefingEvent(date="2026-10-21", start=f"{9 + n:02d}:00", title=f"Event {n}")
        for n in range(EDITION_ROWS_SHOWN + 1)
    ]
    brief = _brief(template_family=EditionFamily.MEMO)
    brief = brief.model_copy(
        update={"payload": brief.payload.model_copy(update={"calendar": events})}
    )

    left_out = (await briefing_view(brief)).left_out

    assert [event.title for event in left_out.events] == [f"Event {EDITION_ROWS_SHOWN}"]


async def test_each_uncomposed_item_carries_the_words_for_its_state() -> None:
    brief = _brief(template_family=EditionFamily.MEMO)
    pool = [
        BriefPoolItem(title="Lease", kind=ItemState.YOU, app="Gmail"),
        BriefPoolItem(title="Export", kind=ItemState.FAILED, app="Drive"),
    ]
    brief = brief.model_copy(
        update={"payload": brief.payload.model_copy(update={"uncomposed": pool})}
    )

    left_out = (await briefing_view(brief)).left_out

    assert [(item.title, item.state_label) for item in left_out.uncomposed] == [
        ("Lease", "Waiting on you"),
        ("Export", "Failed"),
    ]


async def test_a_public_viewer_sees_the_front_page_never_an_item_or_the_calendar() -> None:
    owned = _brief(
        template_family=EditionFamily.MEMO,
        sections=[
            BriefingSection(
                numeral="I",
                title="Waiting on you",
                items=[
                    BriefingItem(
                        text="Reply to Priya", action=BriefAction.REPLY, kind=ItemState.YOU
                    )
                ],
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
