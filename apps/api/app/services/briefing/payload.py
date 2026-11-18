"""Build a brief's payload once, frozen, from everything the run decided: nothing changes it after."""

from dataclasses import dataclass, field

from app.constants.briefing import hue_for_day
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
    BriefingStat,
    BriefingTallies,
    BriefingWeek,
    BriefPoolItem,
    NewStamp,
    UnreadSource,
)
from app.services.briefing.clock import UserClock
from app.services.briefing.edition_draws import EditionDraw
from app.services.briefing.facts import Facts
from app.services.briefing.formats import clock_time
from app.services.briefing.prose import Prose
from app.services.briefing.slots import render_slots


@dataclass(frozen=True)
class PayloadParts:
    """Everything one brief's payload is built from, each decided before it is built.

    stats and calendar are the day's; week is the digest's in their place.
    """

    clock: UserClock
    kicker: str
    prose: Prose
    facts: Facts
    mood: BriefingMood
    edition: EditionDraw
    #: The edition's stamp as a first arrival in the user's collection; None when they hold it.
    new_stamp: NewStamp | None
    recipient_name: str | None
    tallies: BriefingTallies
    sources_read: list[str]
    sources_unavailable: list[UnreadSource]
    uncomposed: list[BriefPoolItem]
    stats: list[BriefingStat] = field(default_factory=list)
    calendar: list[BriefingEvent] = field(default_factory=list)
    week: BriefingWeek | None = None


def _linked_sections(prose: Prose, facts: Facts) -> list[BriefingSection]:
    """Return the sections with each item the message links carrying its link."""
    linked = {todo: prose.links[i] for i, todo in facts.deliverables.items() if i in prose.links}
    return [
        section.model_copy(
            update={
                "items": [
                    item.model_copy(update={"link": linked[item.todo_id]})
                    if item.todo_id in linked
                    else item
                    for item in section.items
                ]
            }
        )
        for section in facts.sections
    ]


def edition_payload(parts: PayloadParts) -> BriefingPayload:
    """Build the brief's edition from its rendered prose, its facts and its drawn edition."""
    clock, prose, edition = parts.clock, parts.prose, parts.edition
    draft = prose.draft
    return BriefingPayload(
        kicker=parts.kicker,
        date=clock.date_str,
        headline=draft.headline,
        lede=draft.lede,
        stats=parts.stats,
        sections=_linked_sections(prose, parts.facts),
        mood=parts.mood,
        caption=draft.caption,
        hue=hue_for_day(clock.day_of_year),
        template_family=edition.family,
        stamp_city=edition.stamp_city,
        artwork_id=edition.artwork_id,
        new_stamp=parts.new_stamp,
        recipient_name=parts.recipient_name,
        generated_at=clock_time(clock.now_local),
        calendar=parts.calendar,
        tallies=parts.tallies,
        week=parts.week,
        sources_read=parts.sources_read,
        sources_unavailable=parts.sources_unavailable,
        message=render_slots(prose.written.message, parts.facts.values, prose.links),
        blocks=edition.drawn,
        undrawn=edition.undrawn,
        uncomposed=parts.uncomposed,
    )
