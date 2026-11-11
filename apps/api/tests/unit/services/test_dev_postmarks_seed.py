"""Dev brief seeding: the brief each seeded day becomes, and what is written for it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    BRIEFING_KIND_WEEKLY,
    DAILY_KICKER,
    POSTAL_FAMILY,
    SECTION_NUMERALS,
    SECTION_TITLES,
    WEEKLY_FAMILY,
    WEEKLY_KICKER,
    BriefAction,
    BriefOutcome,
    SectionKey,
    hue_for_day,
)
from app.constants.notifications import NotificationChannel
from app.models.briefing_models import BriefingPayload, EditionRender
from app.models.user_models import UserDocument
from app.services import dev_postmarks_seed
from app.services.briefing.edition_email import HostedEditionImage
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.dev_postmarks_seed import seed_dev_editions, seed_dev_postmarks
from app.utils.errors import AppError

MODULE = "app.services.dev_postmarks_seed"
STORE = "app.services.briefing.store"
SHORT_LINK = "https://heygaia.link/seededBrief"
LAST_DAY = date(2026, 10, 1)
# Unsorted on purpose, and more cities than seed days, so the cycle and the ordering show.
CITIES = [f"city-{n:02d}" for n in (13, 2, 7, 1, 12, 4, 9, 3, 11, 5, 14, 8, 6, 10)]
PACKED_THURSDAY = 1
EMPTY_INBOX_DAY = 5


@dataclass
class Seeded:
    rendered: list[tuple[BriefingPayload, str]]
    owners: list[str]
    upsert: AsyncMock
    deliver: AsyncMock

    def payloads(self) -> list[BriefingPayload]:
        return [call.args[3] for call in self.upsert.await_args_list]


@pytest.fixture
def user() -> UserDocument:
    return UserDocument.model_validate(
        {"id": str(ObjectId()), "email": "dev@gaia.local", "name": "Ada"}
    )


@pytest.fixture
def seeded() -> Iterator[Seeded]:
    rendered: list[tuple[BriefingPayload, str]] = []
    owners: list[str] = []

    async def fake_host(
        payload: BriefingPayload, *, owner_id: str, render_key: str
    ) -> HostedEditionImage:
        owners.append(owner_id)
        rendered.append((payload, render_key))
        return HostedEditionImage(
            display_url=f"https://cdn.test/{render_key}.png",
            chat_url=f"https://cdn.test/{render_key}.jpg",
        )

    with (
        patch(f"{MODULE}.hosted_stamp_weights", return_value=dict.fromkeys(CITIES, 1)),
        patch(f"{STORE}.host_edition_image", side_effect=fake_host),
        patch(f"{STORE}.optional_short_link", AsyncMock(return_value=SHORT_LINK)),
        patch(
            f"{MODULE}.briefing_repository.briefing_id_for",
            AsyncMock(side_effect=lambda user_id, date, kind: f"brief_{date}"),
        ),
        patch(f"{MODULE}.briefing_repository.upsert_briefing", new_callable=AsyncMock) as upsert,
        patch(
            f"{MODULE}.briefing_repository.set_delivered_channels", new_callable=AsyncMock
        ) as deliver,
    ):
        yield Seeded(rendered, owners, upsert, deliver)


async def test_each_city_gets_one_brief_on_consecutive_days_ending_at_the_anchor(
    user, seeded
) -> None:
    await seed_dev_postmarks(user, len(CITIES))

    payloads = seeded.payloads()
    expected_days = [(LAST_DAY - timedelta(days=i)).isoformat() for i in range(len(CITIES))]
    assert [p.stamp_city for p in payloads] == sorted(CITIES)
    assert [p.date for p in payloads] == expected_days
    assert [p.headline for p in payloads] == [
        dev_postmarks_seed._SEED_DAYS[i % len(dev_postmarks_seed._SEED_DAYS)].headline
        for i in range(len(CITIES))
    ]
    assert all(p.template_family == POSTAL_FAMILY for p in payloads)
    assert all(p.kicker == DAILY_KICKER for p in payloads)
    assert all(p.recipient_name == "Ada" for p in payloads)
    assert seeded.owners == [user.id] * len(CITIES)


async def test_each_brief_is_hosted_then_upserted_and_marked_delivered_under_its_own_render(
    user, seeded
) -> None:
    await seed_dev_postmarks(user, 3)

    keys = [key for _, key in seeded.rendered]
    assert len(set(keys)) == 3
    for (payload, key), upsert_call, deliver_call in zip(
        seeded.rendered, seeded.upsert.await_args_list, seeded.deliver.await_args_list, strict=True
    ):
        assert upsert_call.args == (user.id, payload.date, BRIEFING_KIND_DAILY, payload)
        assert payload.link == SHORT_LINK
        assert upsert_call.kwargs == {
            "briefing_id": f"brief_{payload.date}",
            "edition": EditionRender(image_url=f"https://cdn.test/{key}.png"),
        }
        assert deliver_call.args == (
            user.id,
            payload.date,
            BRIEFING_KIND_DAILY,
            [NotificationChannel.INAPP.value, NotificationChannel.EMAIL.value],
        )


async def test_a_day_with_asks_and_work_reads_as_two_numbered_sections(user, seeded) -> None:
    await seed_dev_postmarks(user, PACKED_THURSDAY + 1)

    seed = dev_postmarks_seed._SEED_DAYS[PACKED_THURSDAY]
    brief = seeded.payloads()[PACKED_THURSDAY]
    day = LAST_DAY - timedelta(days=PACKED_THURSDAY)
    assert [(s.numeral, s.key, s.title) for s in brief.sections] == [
        (SECTION_NUMERALS[0], SectionKey.NEEDS_YOU, SECTION_TITLES[SectionKey.NEEDS_YOU]),
        (SECTION_NUMERALS[1], SectionKey.GAIA_DID, SECTION_TITLES[SectionKey.GAIA_DID]),
    ]
    asks, work = brief.sections
    assert [(i.action, i.text, i.kind) for i in asks.items] == [
        (action, t, "you") for action, t in seed.needs_you
    ]
    assert [(i.outcome, i.text, i.kind) for i in work.items] == [
        (outcome, t, "lookback") for outcome, t in seed.done
    ] + [(BriefOutcome.STARTED, t, "gaia") for t in seed.running]
    assert [(e.date, e.start, e.title, e.location) for e in brief.calendar] == [
        (day.isoformat(), e.start, e.title, e.location) for e in seed.events
    ]
    assert brief.tallies.done_by_you == seed.done_by_you
    assert brief.tallies.done_by_gaia == len(seed.done)
    assert brief.hue == hue_for_day(day.timetuple().tm_yday)
    assert (brief.lede, brief.mood, brief.caption) == (seed.lede, seed.mood, seed.caption)
    assert brief.message == seed.lede
    assert brief.generated_at == "7:58 AM"


async def test_a_day_with_nothing_waiting_drops_the_asks_section(user, seeded) -> None:
    await seed_dev_postmarks(user, EMPTY_INBOX_DAY + 1)

    brief = seeded.payloads()[EMPTY_INBOX_DAY]
    assert [(s.numeral, s.key) for s in brief.sections] == [
        (SECTION_NUMERALS[0], SectionKey.GAIA_DID)
    ]


async def test_every_city_can_be_seeded_but_not_one_more(user, seeded) -> None:
    with pytest.raises(AppError) as exc:
        await seed_dev_postmarks(user, len(CITIES) + 1)

    assert exc.value.status_code == 400
    assert str(len(CITIES) + 1) in exc.value.message
    assert exc.value.why is not None and str(len(CITIES)) in exc.value.why
    assert exc.value.fix is not None and str(len(CITIES)) in exc.value.fix
    assert seeded.rendered == []
    seeded.upsert.assert_not_awaited()

    await seed_dev_postmarks(user, len(CITIES))
    assert seeded.upsert.await_count == len(CITIES)


NON_POSTAL_FAMILIES = sorted(set(DAILY_FAMILY_WEIGHTS) - {POSTAL_FAMILY})


async def test_editions_draw_one_brief_per_other_family_then_a_weekly_recap(user, seeded) -> None:
    await seed_dev_editions(user, 4)

    kinds = [call.args[2] for call in seeded.upsert.await_args_list]
    payloads = seeded.payloads()
    assert kinds == [BRIEFING_KIND_DAILY] * 4 + [BRIEFING_KIND_WEEKLY]
    assert [p.template_family for p in payloads] == [*NON_POSTAL_FAMILIES[:4], WEEKLY_FAMILY]
    assert [p.date for p in payloads[:4]] == [
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-05",
    ]
    assert all(p.stamp_city is None for p in payloads)
    weekly = payloads[-1]
    assert weekly.week is not None and len(weekly.week.days) == 7
    assert [
        (s.key, [(i.text, i.action, i.outcome, i.kind) for i in s.items]) for s in weekly.sections
    ] == [
        (
            SectionKey.NEEDS_YOU,
            [
                ("Offsite venue", BriefAction.REPLY, None, "you"),
                ("New lease terms", BriefAction.APPROVE, None, "you"),
            ],
        ),
        (
            SectionKey.GAIA_DID,
            [
                ("September expenses filed", None, BriefOutcome.FINISHED, "lookback"),
                ("1:1 with Sam, now 3:30 PM", None, BriefOutcome.BOOKED, "lookback"),
                ("October invoice to Acme", None, BriefOutcome.SENT, "lookback"),
                ("Check-in for TP 1361", None, BriefOutcome.BOOKED, "lookback"),
            ],
        ),
    ]
    assert seeded.deliver.await_count == 5


async def test_no_editions_seeds_nothing_and_too_many_is_refused(user, seeded) -> None:
    await seed_dev_editions(user, 0)
    seeded.upsert.assert_not_awaited()

    with pytest.raises(AppError) as exc:
        await seed_dev_editions(user, len(NON_POSTAL_FAMILIES) + 1)

    assert exc.value.status_code == 400
    assert seeded.rendered == []


async def test_a_seed_count_past_the_daily_families_is_refused_naming_the_limit(
    user, seeded
) -> None:
    families = len(set(DAILY_FAMILY_WEIGHTS) - {POSTAL_FAMILY})

    with pytest.raises(AppError) as raised:
        await seed_dev_editions(user, families + 1)

    assert raised.value.message == f"Cannot seed {families + 1} editions"
    assert raised.value.why == f"there are only {families} daily edition families besides Air Mail"
    assert raised.value.fix == f"ask for at most {families}"
    seeded.upsert.assert_not_awaited()


async def test_the_weekly_recap_is_the_one_seeded_week_in_full(user, seeded) -> None:
    await seed_dev_editions(user, 1)

    weekly = seeded.payloads()[-1]
    assert (weekly.kicker, weekly.date, weekly.template_family) == (
        WEEKLY_KICKER,
        "2026-10-11",
        WEEKLY_FAMILY,
    )
    assert (weekly.headline, weekly.lede, weekly.message) == (
        "A steady week: the release shipped and two decisions are still open",
        "You closed 14 todos and I handled 22; the offsite venue and the lease still wait.",
        "You closed 14 todos and I handled 22; the offsite venue and the lease still wait.",
    )
    assert (weekly.mood, weekly.caption, weekly.hue) == (
        "clear",
        "Two decisions and the week is closed.",
        hue_for_day(date(2026, 10, 11).timetuple().tm_yday),
    )
    assert (weekly.recipient_name, weekly.generated_at) == ("Ada", "7:58 AM")
    assert (weekly.tallies.done_by_you, weekly.tallies.done_by_gaia) == (14, 22)
    asks, work = weekly.sections
    assert [(s.numeral, s.key) for s in weekly.sections] == [
        (SECTION_NUMERALS[0], SectionKey.NEEDS_YOU),
        (SECTION_NUMERALS[1], SectionKey.GAIA_DID),
    ]
    assert [(i.text, i.kind) for i in asks.items] == [
        ("Confirm the offsite venue", "you"),
        ("Accept the new lease terms", "you"),
    ]
    shipped = [seed.done[0] for seed in dev_postmarks_seed._SEED_DAYS[:4]]
    assert [(i.text, i.kind) for i in work.items] == [(t, "lookback") for t in shipped]
    assert weekly.week is not None
    assert weekly.week.shipped == shipped
    assert weekly.week.handled == [
        "Rescheduled 3 meetings",
        "Paid 2 invoices",
        "Archived 120 emails",
    ]
    assert [(e.date, e.start, e.title) for e in weekly.week.ahead] == [
        ("2026-10-12", "10:00", "Quarterly planning"),
        ("2026-10-14", "18:40", "Flight to Lisbon"),
    ]
