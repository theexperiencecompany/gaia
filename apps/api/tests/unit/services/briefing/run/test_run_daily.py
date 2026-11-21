"""A daily brief run end to end: what is stored, delivered and drawn as its edition."""

from __future__ import annotations

import pytest
from tests.briefing_run_world import (
    BRIEF_ID,
    BRIEF_LINK,
    CHAT,
    CHAT_EDITION_URL,
    DATE,
    EDITION_KEY,
    EDITION_URL,
    EVENT,
    ORCHESTRATED,
    PROGRESS,
    RENDERED,
    TZ,
    USER,
    VOICE,
    World,
    brief_work,
    composed,
    delivered_plan,
    skipped,
    stored_brief,
    weekly_reply,
    with_block,
)

from app.agents.prompts.brief_fact_prompts import UNNAMED_READER
from app.constants.briefing import (
    BriefForm,
    BriefingBag,
    BriefingKind,
    BriefingRunOutcome,
    EditionChoice,
    EditionFamily,
)
from app.constants.notifications import (
    NotificationKind,
    ProactiveMessageClass,
)
from app.models.brief_document_models import (
    EditionRender,
)
from app.models.brief_payload_models import (
    BriefingTallies,
    NewStamp,
    UnreadSource,
)
from app.models.briefing_state_models import (
    ShuffleBag,
)
from app.models.scout_models import (
    ScoutSkipReason,
)
from app.models.short_link_models import ShortLinkTargetType
from app.models.user_models import UserDocument
from app.services.briefing.calendar_read import CalendarGap
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.artworks import artwork_weights
from app.services.briefing.editions.stamps import stamp_weights
from app.services.briefing.pipeline import run_brief
from app.services.briefing.prose import reader_block
from app.utils.message_breaks import split_message_bubbles

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestADailyBrief:
    async def test_it_is_stored_then_delivered_in_app_by_email_and_as_a_chat_image(
        self, world: World
    ) -> None:
        world.track(brief_work())

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        payload = world.stored()
        assert payload.headline == "Your morning, sorted"
        assert (payload.template_family, payload.stamp_city, payload.artwork_id) == (
            "memo",
            None,
            None,
        )
        assert "stamp_city" not in world.bags and "artwork" not in world.bags
        assert payload.calendar == [EVENT]
        # The user's Gym and GAIA's investor update, both done since yesterday's brief.
        assert payload.tallies == BriefingTallies(done_by_you=1, done_by_gaia=1)
        assert world.fact("Sequoia").time == "11:00 AM"
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Investor update"]),
        ]
        assert [i.todo_id for s in payload.sections for i in s.items] == ["b1", "c1"]
        message = "Approve the Priya reply\nInvestor update\nSequoia"
        assert payload.message == message
        assert world.today().edition == EditionRender(
            key=EDITION_KEY, fold=0.3, paper=[0.1, 0.2, 0.9, 0.8]
        )
        world.store_edition.assert_awaited_once_with(USER, BRIEF_ID, RENDERED.image)
        request = world.notify.await_args.args[0]
        assert request.details.card.edition.image_url.startswith(EDITION_URL)
        # One URL, minted before the render: the edition's codes, the email image and the chat post.
        world.mint.assert_awaited_with(USER, ShortLinkTargetType.BRIEFING, BRIEF_ID)
        assert world.render.await_args.args[1] == BRIEF_LINK
        assert request.details.brief_url == BRIEF_LINK
        assert request.content.actions[0].config.redirect.url == f"/brief/{BRIEF_ID}"
        assert [c.channel_type for c in request.channels] == ORCHESTRATED
        assert request.details.kind == NotificationKind.BRIEFING_DAILY
        # GAIA's Briefings-conversation message carries the same folded card the notification does.
        user_id, briefing_id, text, card = world.brief_message.await_args.args
        assert (user_id, briefing_id, text) == (USER, BRIEF_ID, message)
        assert (card.briefing_id, card.kind) == (BRIEF_ID, "daily")
        assert card.needs_you_count == 1
        assert card.edition is not None and card.edition.image_url.startswith(EDITION_URL)
        assert request.details.card == card
        assert request.content.body == message
        assert request.content.rich_content is None
        world.render.assert_awaited_once()
        post = world.post.await_args.kwargs
        assert post["channel"] == CHAT
        assert post["message"].image_url.startswith(CHAT_EDITION_URL)
        assert split_message_bubbles(post["message"].text) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {BRIEF_LINK}",
        ]
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]

    async def test_without_a_chat_platform_nothing_is_posted(self, world: World) -> None:
        world.chat = None

        await run_brief(USER, BriefingKind.DAILY)

        world.render.assert_awaited_once()
        world.post.assert_not_awaited()
        assert world.delivered_to() == ORCHESTRATED

    async def test_a_rerun_stores_its_edition_over_the_one_its_brief_had(
        self, world: World
    ) -> None:
        world.notify.side_effect = [RuntimeError("orchestrator down"), world.notify.return_value]

        await run_brief(USER, BriefingKind.DAILY)

        stored = [c.args[:2] for c in world.store_edition.await_args_list]
        assert stored == [(USER, BRIEF_ID), (USER, BRIEF_ID)]

    async def test_the_edition_is_addressed_to_the_user_by_name(self, world: World) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().recipient_name == "Ada"
        assert world.voice_prompt.call_args.kwargs["blocks"].reader == reader_block(world.user)

    async def test_a_user_who_gave_no_name_is_addressed_by_none(self, world: World) -> None:
        """Regression: the brief greeted "Dear Delivered", a name guessed from delivered+dev@resend.dev."""
        world.user = UserDocument(id=USER, timezone=TZ, email="delivered+dev@resend.dev")

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().recipient_name is None
        assert world.pool is not None and world.pool.context.reader == UNNAMED_READER
        assert "Delivered" not in world.voice.await_args.args[1]

    async def test_the_pool_is_composed_for_the_reader_on_their_day_beside_recent_openings(
        self, world: World
    ) -> None:
        world.briefs_read(
            [stored_brief("2026-10-13", BriefForm.EDITION, message="Priya replied overnight.")]
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, context.clock.date_str, str(context.clock.tz)) == (
            "Ada",
            DATE,
            TZ,
        )
        assert (context.calendar, context.calendar_span) == (1, "today")
        assert context.recent_openings == ["Priya replied overnight."]

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_user_with_no_name_or_timezone_is_composed_for_as_the_user_in_utc(
        self, world: World, kind: BriefingKind
    ) -> None:
        world.replies = [weekly_reply() if kind is BriefingKind.WEEKLY else VOICE]
        world.user = UserDocument(id=USER, email="delivered+dev@resend.dev")

        await run_brief(USER, kind)

        assert world.pool is not None
        context = world.pool.context
        assert (context.reader, context.clock.date_str, str(context.clock.tz)) == (
            UNNAMED_READER,
            DATE,
            "UTC",
        )

    async def test_an_empty_day_stays_in_app_and_spends_no_draw(self, world: World) -> None:
        """Nothing needs the user, nothing is on the calendar, nothing ran overnight."""
        bags_before = dict(world.bags)
        world.calendar = []

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.sections == [] and payload.calendar == []
        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]
        world.post.assert_not_awaited()
        assert world.bags == bags_before

    async def test_the_brief_is_dated_and_stamped_in_the_users_timezone(self, world: World) -> None:
        world.track(brief_work())

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert (payload.kicker, payload.date, payload.generated_at) == (
            "THE MORNING BRIEF",
            DATE,
            "7:05 AM",
        )
        assert (payload.hue, payload.mood, payload.caption) == (79, "packed", "Onward.")
        assert [(s.value, s.label) for s in payload.stats] == [
            ("1", "done since last brief"),
            ("1", "waiting on you"),
        ]

    async def test_delivery_opens_the_brief_and_posts_the_image_as_the_daily_brief(
        self, world: World
    ) -> None:
        world.track(brief_work())

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [c.args[0] for c in world.render.await_args_list] == [payload]
        request = world.notify.await_args.args[0]
        assert request.priority == 2
        action = request.content.actions[0]
        assert (action.label, action.style) == ("Open briefing", "primary")
        redirect = action.config.redirect
        assert (redirect.open_in_new_tab, redirect.close_notification) == (False, True)
        card = request.details.card
        assert (card.briefing_id, card.date) == (BRIEF_ID, DATE)
        post = world.post.await_args.kwargs
        assert post["user"].user_id == USER
        assert post["message"].origin == "daily brief"
        assert post["message"].notice_id == f"brief:{BRIEF_ID}:telegram"
        assert post["message"].message_class is ProactiveMessageClass.ROUTINE

    @pytest.mark.parametrize(
        "user",
        [
            UserDocument(
                id=USER, timezone="UTC", email="a@b.c", notification_channel_prefs={"email": False}
            ),
            UserDocument(id=USER, timezone=TZ, email=None),
            UserDocument(id=USER, timezone=TZ, email="   "),
        ],
        ids=["turned-off", "no-address", "blank-address"],
    )
    async def test_email_is_left_out_when_it_is_off_or_has_no_address(
        self, world: World, user: UserDocument
    ) -> None:
        world.user = user

        await run_brief(USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert [c.channel_type for c in request.channels] == ["inapp"]

    async def test_a_calendar_that_did_not_answer_is_named_unavailable_never_empty(
        self, world: World
    ) -> None:
        """Regression: a calendar read that failed reached the voice as a day with nothing on it."""
        world.track(brief_work())
        world.calendar = CalendarGap.UNAVAILABLE

        await run_brief(USER, BriefingKind.DAILY)

        assert world.pool is not None and world.pool.context.calendar is CalendarGap.UNAVAILABLE
        assert world.fact_sources is not None
        assert world.fact_sources.calendar.gap is CalendarGap.UNAVAILABLE
        assert [(u.app, u.reason) for u in world.stored().sources_unavailable] == [
            ("Google Calendar", ScoutSkipReason.FAILED)
        ]

    async def test_an_app_the_brief_could_not_read_is_named_to_the_composer_and_the_voice(
        self, world: World
    ) -> None:
        world.track(brief_work())
        world.scouts = [skipped("Notion")]
        notion = [UnreadSource(app="Notion", reason=ScoutSkipReason.FAILED)]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.pool is not None and world.pool.context.unread == notion
        assert world.fact_sources is not None and world.fact_sources.unread == notion
        assert world.stored().sources_unavailable == notion


class TestTheEdition:
    async def test_an_air_mail_brief_records_its_stamp_city_and_advances_the_stored_pass(
        self, world: World
    ) -> None:
        world.family_first(EditionFamily.POSTAL)
        seeded = world.bags[BriefingBag.EDITION_FAMILY].order

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.template_family == "postal"
        # The stored pass was read and advanced, not reshuffled from scratch.
        assert world.bags[BriefingBag.EDITION_FAMILY] == ShuffleBag(order=seeded, index=1)
        assert payload.stamp_city in stamp_weights()
        assert world.bags[BriefingBag.STAMP_CITY].order[0] == payload.stamp_city

    @pytest.mark.parametrize(
        ("family", "bag"),
        [
            (EditionFamily.POSTAL, BriefingBag.STAMP_CITY),
            (EditionFamily.ALMANAC, BriefingBag.ARTWORK),
        ],
    )
    async def test_a_brief_that_fails_to_deliver_spends_no_draw(
        self, world: World, family: EditionFamily, bag: BriefingBag
    ) -> None:
        """A draw is spent only by a brief that went out: a failed run burns no member."""
        world.family_first(family)
        family_before = world.bags[BriefingBag.EDITION_FAMILY]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError, match="orchestrator down"):
            await run_brief(USER, BriefingKind.DAILY)

        assert world.bags[BriefingBag.EDITION_FAMILY] == family_before
        assert bag not in world.bags

    async def test_a_first_stamp_is_announced_on_every_channel(self, world: World) -> None:
        world.family_first(EditionFamily.POSTAL)
        world.stamp_first("tokyo")

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().new_stamp == NewStamp(
            city="Tokyo", country="Japan", collected=1, total=85
        )
        line = "New stamp: Tokyo, Japan. 1 of 85 collected. [See your stamps]("
        assert line in world.post.await_args.kwargs["message"].text
        assert line in world.notify.await_args.args[0].content.body
        assert world.capture.call_args.args[1].stamp_collected is True

    async def test_a_city_already_collected_is_not_announced_again(self, world: World) -> None:
        world.family_first(EditionFamily.POSTAL)
        world.stamp_first("tokyo")
        collected = stored_brief(
            "2026-09-01",
            BriefForm.EDITION,
            template_family=EditionFamily.POSTAL,
            stamp_city="tokyo",
            headline="Tokyo, by air",
        )
        world.briefs[collected.id] = collected.model_copy(update={"delivery": delivered_plan()})

        await run_brief(USER, BriefingKind.DAILY)

        assert (world.stored().stamp_city, world.stored().new_stamp) == ("tokyo", None)
        assert "New stamp" not in world.post.await_args.kwargs["message"].text

    async def test_the_next_framed_brief_hangs_the_next_painting_of_the_pass(
        self, world: World
    ) -> None:
        world.family_first(EditionFamily.EXHIBITION)
        order = sorted(artwork_weights())
        world.bags[BriefingBag.ARTWORK] = ShuffleBag(order=order, index=3)

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().artwork_id == order[3]
        assert world.bags[BriefingBag.ARTWORK] == ShuffleBag(order=order, index=4)

    async def test_a_block_the_drawn_edition_cannot_draw_moves_to_the_briefs_page(
        self, world: World
    ) -> None:
        world.track(brief_work())
        world.composer.side_effect = with_block(
            composed({"Waiting": ["Approve the Priya reply"]}), PROGRESS
        )
        # Menu alone is on, and it draws no progress block.
        world.state.editions = {
            family: EditionChoice.OFF for family in DAILY_FAMILY_WEIGHTS if family != "menu"
        }

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [b.kind for b in payload.undrawn] == ["progress"]
        assert [b.kind for b in payload.blocks] == ["items"]

    async def test_a_brief_its_only_edition_cannot_draw_is_still_sent(self, world: World) -> None:
        """Regression (#1804 review): with only Menu on, a progress-only brief drew nothing and was never pushed."""
        world.calendar = []
        world.track(brief_work())
        world.state.editions = {
            family: EditionChoice.OFF for family in DAILY_FAMILY_WEIGHTS if family != "menu"
        }
        world.composer.side_effect = lambda schema, _prompt, **_k: schema.model_validate(
            {"blocks": [PROGRESS]}
        )

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert (payload.template_family, payload.blocks) == ("menu", [])
        assert [b.kind for b in payload.undrawn] == ["progress"]
        world.post.assert_awaited_once()
