"""Dev-only seeding of past briefs: Air Mail ones for Postmarks, other families for the archive.

Each seeded day is a plausible daily brief (asks, calendar, overnight work), rendered
and hosted exactly as a sent brief is, and written through the real briefings
repository. Postmarks draws each in the postal family under a distinct city stamp;
editions draws one per other daily family, plus a weekly recap. Fixed dates key the
(user, date, kind) upsert, so a re-run on any day rewrites the same rows.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import uuid4

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_KICKER,
    NEEDS_YOU_SECTION_TITLE,
    POSTAL_FAMILY,
    SECTION_NUMERALS,
    WEEKLY_FAMILY,
    WEEKLY_KICKER,
    WORK_SECTION_TITLE,
    hue_for_day,
)
from app.constants.notifications import NotificationChannel
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingEvent,
    BriefingItem,
    BriefingKind,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
    BriefingTallies,
    BriefingWeek,
    BriefingWeekDay,
)
from app.models.user_models import UserDocument
from app.services.briefing.edition_email import host_edition_image
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.utils.errors import create_error

_SEEDED_CHANNELS: list[str] = [NotificationChannel.INAPP.value, NotificationChannel.EMAIL.value]
# Anchored, not today-relative: a today-relative range would add a brief on every new day.
_LAST_SEEDED_DATE = date(2026, 10, 1)
# Editions run forward from the day after the last postmark; the recap closes their week.
_FIRST_EDITION_DATE = date(2026, 10, 2)
_WEEKLY_SEEDED_DATE = date(2026, 10, 11)
_WEEKLY_HEADLINE = "A steady week: the release shipped and two decisions are still open"
_WEEKLY_LEDE = "You closed 14 todos and I handled 22; the offsite venue and the lease still wait."
_WEEKLY_DAYS = ((2, 4), (3, 5), (1, 3), (4, 2), (2, 6), (0, 1), (2, 1))
_GENERATED_AT = "7:58 AM"


@dataclass(frozen=True)
class _SeedEvent:
    start: str | None
    title: str
    location: str | None = None


@dataclass(frozen=True)
class _SeedDay:
    """One morning's brief: what waits on the reader, their calendar, and GAIA's night."""

    headline: str
    lede: str
    mood: BriefingMood
    caption: str
    needs_you: tuple[str, ...]
    events: tuple[_SeedEvent, ...]
    done: tuple[str, ...]
    running: tuple[str, ...] = ()
    done_by_you: int = 0


_SEED_DAYS: tuple[_SeedDay, ...] = (
    _SeedDay(
        headline="Two signatures and a quiet afternoon",
        lede="The Northwind contract is ready to sign, and nothing is booked after 2 PM.",
        mood="clear",
        caption="Sign early, then take the afternoon back.",
        needs_you=("Sign the Northwind services agreement", "Approve Priya's travel request"),
        events=(_SeedEvent("10:00", "Design review", "Studio 3"),),
        done=("Filed September expenses", "Drafted replies to 6 newsletters you follow"),
        done_by_you=3,
    ),
    _SeedDay(
        headline="A packed Thursday, mostly meetings",
        lede="Five calls back to back; I moved the 1:1 with Sam so you get lunch.",
        mood="packed",
        caption="Eat before the 1 PM.",
        needs_you=("Confirm the offsite venue by noon",),
        events=(
            _SeedEvent("09:30", "Standup"),
            _SeedEvent("11:00", "Quarterly planning", "Boardroom"),
            _SeedEvent("13:00", "Customer call: Halden Labs"),
            _SeedEvent("15:30", "1:1 with Sam"),
        ),
        done=("Rescheduled the 1:1 with Sam to 3:30 PM", "Summarised the Halden Labs thread"),
        running=("Comparing three offsite venue quotes",),
        done_by_you=1,
    ),
    _SeedDay(
        headline="The invoice went out, the bug did not come back",
        lede="Acme paid overnight and the login fix held through the weekend traffic.",
        mood="clear",
        caption="A clean slate for Monday.",
        needs_you=("Review the draft pricing page copy",),
        events=(_SeedEvent("14:00", "Pricing sync", "Zoom"),),
        done=(
            "Sent the October invoice to Acme",
            "Checked error rates after the login fix",
            "Archived 41 promotional emails",
        ),
        done_by_you=2,
    ),
    _SeedDay(
        headline="Your flight to Lisbon is on time",
        lede="Boarding at 6:40 PM from gate B12; the hotel confirmed early check-in.",
        mood="clear",
        caption="Pack the charger this time.",
        needs_you=("Choose a seat for the return flight",),
        events=(
            _SeedEvent("12:30", "Lunch with Maya", "Café Lumen"),
            _SeedEvent("18:40", "Flight TP 1361 to Lisbon", "Terminal 2"),
        ),
        done=("Checked you in for TP 1361", "Shared the itinerary with Maya"),
        running=("Finding a dinner spot near the hotel",),
    ),
    _SeedDay(
        headline="Three replies are waiting on you",
        lede="Recruiting, the landlord and the conference talk all need a yes or no.",
        mood="packed",
        caption="Ten minutes clears all three.",
        needs_you=(
            "Respond to Jordan about the senior engineer offer",
            "Accept the new lease terms",
            "Decide on the conference talk slot",
        ),
        events=(_SeedEvent("16:00", "Interview: frontend candidate"),),
        done=("Collected the interview scorecards",),
        done_by_you=4,
    ),
    _SeedDay(
        headline="Nothing on the calendar, plenty done",
        lede="A free Saturday; overnight I cleared the reading list and booked the dentist.",
        mood="idle",
        caption="Enjoy the slow one.",
        needs_you=(),
        events=(),
        done=(
            "Booked the dentist for Tuesday 9 AM",
            "Saved 4 long reads to your reading list",
            "Renewed the domain for another year",
        ),
    ),
    _SeedDay(
        headline="The board deck needs your numbers",
        lede="Slides 4 to 9 are drafted; the revenue chart is waiting on the final close.",
        mood="packed",
        caption="Numbers first, polish later.",
        needs_you=("Review the board deck revenue slide", "Send the final close figures to Elena"),
        events=(
            _SeedEvent("10:30", "Finance sync", "Room 2B"),
            _SeedEvent("17:00", "Board prep with Elena"),
        ),
        done=("Drafted slides 4 to 9 of the board deck",),
        running=("Reconciling September revenue",),
        done_by_you=2,
    ),
    _SeedDay(
        headline="Your mother's birthday is Sunday",
        lede="The flowers are ordered for Saturday delivery; the card still needs your words.",
        mood="clear",
        caption="Write it from the heart.",
        needs_you=("Sign the birthday card before Friday",),
        events=(_SeedEvent("19:00", "Dinner with Alex", "Osteria Nove"),),
        done=("Ordered flowers for Saturday delivery", "Reserved a table at Osteria Nove"),
        done_by_you=1,
    ),
    _SeedDay(
        headline="The release shipped while you slept",
        lede="Version 2.4 is live for everyone, and the changelog went out at 6 AM.",
        mood="clear",
        caption="Celebrate the team at standup.",
        needs_you=("Approve the blog post about 2.4",),
        events=(_SeedEvent("09:30", "Standup"), _SeedEvent("15:00", "Retro", "Zoom")),
        done=(
            "Published the 2.4 changelog",
            "Posted the release note in #general",
            "Closed 12 resolved issues",
        ),
        done_by_you=5,
    ),
    _SeedDay(
        headline="A renewal is due before Friday",
        lede="The insurance policy lapses on the 3rd; the cheaper quote is ready to compare.",
        mood="clear",
        caption="One decision, then you are covered.",
        needs_you=("Renew the home insurance policy",),
        events=(_SeedEvent("11:00", "Call with the accountant"),),
        done=("Pulled three insurance quotes", "Paid the electricity bill"),
        running=("Checking the accountant's tax questions",),
        done_by_you=2,
    ),
    _SeedDay(
        headline="Gym at seven, deep work until noon",
        lede="I blocked the morning for the proposal and muted Slack until 12.",
        mood="clear",
        caption="Protect the morning.",
        needs_you=(),
        events=(
            _SeedEvent("07:00", "Gym", "Pulse Fitness"),
            _SeedEvent("08:30", "Focus: grant proposal"),
            _SeedEvent("14:00", "Advisor check-in"),
        ),
        done=("Blocked 8:30 to 12 for the proposal", "Outlined the grant proposal sections"),
        done_by_you=3,
    ),
    _SeedDay(
        headline="One payment failed overnight",
        lede="The card on the design tool expired; everything else renewed fine.",
        mood="clear",
        caption="Update the card and it retries.",
        needs_you=("Authorize the new card for Figma billing",),
        events=(_SeedEvent("13:00", "Lunch and learn", "Kitchen"),),
        done=("Renewed the cloud storage plan", "Exported last month's receipts"),
        done_by_you=1,
    ),
)


def _brief_payload(
    day: date, seed: _SeedDay, user: UserDocument, family: str, city_slug: str | None = None
) -> BriefingPayload:
    iso_day = day.isoformat()
    titled_items = (
        (NEEDS_YOU_SECTION_TITLE, [BriefingItem(text=text, kind="you") for text in seed.needs_you]),
        (
            WORK_SECTION_TITLE,
            [BriefingItem(text=text, kind="lookback") for text in seed.done]
            + [BriefingItem(text=text, kind="gaia") for text in seed.running],
        ),
    )
    filled = [(title, items) for title, items in titled_items if items]
    return BriefingPayload(
        kicker=DAILY_KICKER,
        date=iso_day,
        headline=seed.headline,
        lede=seed.lede,
        sections=[
            BriefingSection(numeral=SECTION_NUMERALS[i], title=title, items=items)
            for i, (title, items) in enumerate(filled)
        ],
        mood=seed.mood,
        caption=seed.caption,
        hue=hue_for_day(day.timetuple().tm_yday),
        template_family=family,
        stamp_city=city_slug,
        recipient_name=user.name,
        generated_at=_GENERATED_AT,
        calendar=[
            BriefingEvent(date=iso_day, start=e.start, title=e.title, location=e.location)
            for e in seed.events
        ],
        tallies=BriefingTallies(done_by_you=seed.done_by_you, done_by_gaia=len(seed.done)),
        message=seed.lede,
    )


async def seed_dev_postmarks(user: UserDocument, count: int) -> None:
    """Render, host and upsert count delivered postal briefs on consecutive days, one city each."""
    cities = sorted(hosted_stamp_weights())
    if count > len(cities):
        raise create_error(
            message=f"Cannot seed {count} postmarks",
            why=f"only {len(cities)} city stamps have hosted art",
            fix=f"ask for at most {len(cities)}",
            status_code=400,
        )
    for days_before, slug in enumerate(cities[:count]):
        day = _LAST_SEEDED_DATE - timedelta(days=days_before)
        seed = _SEED_DAYS[days_before % len(_SEED_DAYS)]
        await _store(
            user, _brief_payload(day, seed, user, POSTAL_FAMILY, slug), BRIEFING_KIND_DAILY
        )


async def seed_dev_editions(user: UserDocument, count: int) -> None:
    """Render, host and upsert count daily briefs, one per non-postal family, then a weekly recap."""
    families = sorted(set(DAILY_FAMILY_WEIGHTS) - {POSTAL_FAMILY})
    if count > len(families):
        raise create_error(
            message=f"Cannot seed {count} editions",
            why=f"there are only {len(families)} daily edition families besides Air Mail",
            fix=f"ask for at most {len(families)}",
            status_code=400,
        )
    if count == 0:
        return
    for offset, family in enumerate(families[:count]):
        day = _FIRST_EDITION_DATE + timedelta(days=offset)
        seed = _SEED_DAYS[offset % len(_SEED_DAYS)]
        await _store(user, _brief_payload(day, seed, user, family), BRIEFING_KIND_DAILY)
    await _store(user, _weekly_payload(user), BRIEFING_KIND_WEEKLY)


def _weekly_payload(user: UserDocument) -> BriefingPayload:
    iso_day = _WEEKLY_SEEDED_DATE.isoformat()
    shipped = [seed.done[0] for seed in _SEED_DAYS[:4]]
    return BriefingPayload(
        kicker=WEEKLY_KICKER,
        date=iso_day,
        headline=_WEEKLY_HEADLINE,
        lede=_WEEKLY_LEDE,
        sections=[
            BriefingSection(
                numeral=SECTION_NUMERALS[0],
                title=NEEDS_YOU_SECTION_TITLE,
                items=[
                    BriefingItem(text="Confirm the offsite venue", kind="you"),
                    BriefingItem(text="Accept the new lease terms", kind="you"),
                ],
            ),
            BriefingSection(
                numeral=SECTION_NUMERALS[1],
                title=WORK_SECTION_TITLE,
                items=[BriefingItem(text=text, kind="lookback") for text in shipped],
            ),
        ],
        mood="clear",
        caption="Two decisions and the week is closed.",
        hue=hue_for_day(_WEEKLY_SEEDED_DATE.timetuple().tm_yday),
        template_family=WEEKLY_FAMILY,
        recipient_name=user.name,
        generated_at=_GENERATED_AT,
        tallies=BriefingTallies(done_by_you=14, done_by_gaia=22),
        week=BriefingWeek(
            days=[BriefingWeekDay(you=you, gaia=gaia) for you, gaia in _WEEKLY_DAYS],
            shipped=shipped,
            handled=["Rescheduled 3 meetings", "Paid 2 invoices", "Archived 120 emails"],
            ahead=[
                BriefingEvent(date="2026-10-12", start="10:00", title="Quarterly planning"),
                BriefingEvent(date="2026-10-14", start="18:40", title="Flight to Lisbon"),
            ],
        ),
        message=_WEEKLY_LEDE,
    )


async def _store(user: UserDocument, payload: BriefingPayload, kind: BriefingKind) -> None:
    """Render and host the edition, then upsert the brief as delivered in-app and by email."""
    image = await host_edition_image(payload, render_key=uuid4().hex)
    await briefing_repository.upsert_briefing(
        user.id,
        payload.date,
        kind,
        payload,
        edition_image_url=image.display_url,
        edition_fold=image.fold,
    )
    await briefing_repository.set_delivered_channels(user.id, payload.date, kind, _SEEDED_CHANNELS)
