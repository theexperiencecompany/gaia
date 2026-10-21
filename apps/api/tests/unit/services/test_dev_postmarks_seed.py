"""Dev postmark seeding: the brief each seeded day becomes, and what is written for it."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.constants.briefing import (
    BRIEFING_KIND_DAILY,
    DAILY_KICKER,
    NEEDS_YOU_SECTION_TITLE,
    POSTAL_FAMILY,
    SECTION_NUMERALS,
    WORK_SECTION_TITLE,
    hue_for_day,
)
from app.constants.notifications import NotificationChannel
from app.models.briefing_models import BriefingPayload
from app.models.user_models import UserDocument
from app.services import dev_postmarks_seed
from app.services.briefing.edition_email import HostedEditionImage
from app.services.dev_postmarks_seed import seed_dev_postmarks
from app.utils.errors import AppError

MODULE = "app.services.dev_postmarks_seed"
LAST_DAY = date(2026, 10, 1)
# Unsorted on purpose, and more cities than seed days, so the cycle and the ordering show.
CITIES = [f"city-{n:02d}" for n in (13, 2, 7, 1, 12, 4, 9, 3, 11, 5, 14, 8, 6, 10)]
PACKED_THURSDAY = 1
EMPTY_INBOX_DAY = 5


@dataclass
class Seeded:
    rendered: list[tuple[BriefingPayload, str]]
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

    async def fake_host(payload: BriefingPayload, *, render_key: str) -> HostedEditionImage:
        rendered.append((payload, render_key))
        return HostedEditionImage(
            display_url=f"https://cdn.test/{render_key}.png",
            chat_url=f"https://cdn.test/{render_key}.jpg",
        )

    with (
        patch(f"{MODULE}.hosted_stamp_weights", return_value=dict.fromkeys(CITIES, 1)),
        patch(f"{MODULE}.host_edition_image", side_effect=fake_host),
        patch(f"{MODULE}.briefing_repository.upsert_briefing", new_callable=AsyncMock) as upsert,
        patch(
            f"{MODULE}.briefing_repository.set_delivered_channels", new_callable=AsyncMock
        ) as deliver,
    ):
        yield Seeded(rendered, upsert, deliver)


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
        assert upsert_call.kwargs == {"edition_image_url": f"https://cdn.test/{key}.png"}
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
    assert [(s.numeral, s.title) for s in brief.sections] == [
        (SECTION_NUMERALS[0], NEEDS_YOU_SECTION_TITLE),
        (SECTION_NUMERALS[1], WORK_SECTION_TITLE),
    ]
    asks, work = brief.sections
    assert [(i.text, i.kind) for i in asks.items] == [(t, "you") for t in seed.needs_you]
    assert [(i.text, i.kind) for i in work.items] == [(t, "lookback") for t in seed.done] + [
        (t, "gaia") for t in seed.running
    ]
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
    assert [(s.numeral, s.title) for s in brief.sections] == [
        (SECTION_NUMERALS[0], WORK_SECTION_TITLE)
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
