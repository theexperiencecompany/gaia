"""How a run ends: skipped, already delivered, failed, resumed mid-delivery, or timed out."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from playwright._impl._errors import TargetClosedError
import pytest
from tests.briefing_run_world import (
    BRIEF_ID,
    BRIEF_LINK,
    CHAT,
    CHAT_EDITION_URL,
    DATE,
    DIGEST_REPORT,
    LOGIN,
    NOW,
    ORCHESTRATED,
    RENDERED,
    TZ,
    USER,
    World,
    delivered,
    dormant,
    held,
    idle_day,
    notified,
    quiet_day,
    scouted,
    stored_brief,
    winback,
)
from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.constants.briefing import (
    BRIEF_NOTIFICATION_PRIORITY,
    BRIEF_RUN_LOCK_LEASE_SECONDS,
    BRIEF_RUN_LOCK_MAX_HOLD_SECONDS,
    BRIEF_RUN_LOCK_PREFIX,
    BRIEF_RUN_LOCK_RENEW_SECONDS,
    IDLE_DORMANT_DAYS,
    BriefForm,
    BriefingBag,
    BriefingKind,
    BriefingRunOutcome,
)
from app.constants.notifications import (
    NotificationKind,
    ProactiveMessageClass,
)
from app.models.brief_document_models import (
    BriefDelivery,
    DeliveryStep,
)
from app.models.brief_payload_models import BriefingMood
from app.models.notification.notification_models import (
    ActionStyle,
    ChannelDeliveryStatus,
    NotificationStatus,
    RedirectConfig,
    notification_id,
)
from app.models.user_models import UserDocument
from app.services.briefing import delivery, errors
from app.services.briefing.kinds import KIND_SPECS
from app.services.briefing.pipeline import run_brief
from app.services.briefing.wind_down import ladder_state
from app.services.outbound_delivery import OutboundResult
from app.utils.auth_utils import build_user_context
from app.utils.message_breaks import split_message_bubbles

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestHowARunEnds:
    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_an_unknown_user_fails_loud(self, world: World, kind: BriefingKind) -> None:
        world.user = UserDocument(id=make_user_id(), timezone=TZ)

        with pytest.raises(errors.BriefingGenerationError, match=f"unknown user {USER}$"):
            await run_brief(USER, kind)

        world.voice.assert_not_awaited()

    async def test_a_dormant_user_without_activity_is_skipped_before_the_model(
        self, world: World
    ) -> None:
        dormant(world)

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.DORMANT

        world.voice.assert_not_awaited()
        world.nothing_sent()

    async def test_an_ignored_winback_backs_off(self, world: World) -> None:
        winback(world)
        last = world.briefs["b-2026-10-13-daily"]
        last.payload = last.payload.model_copy(update={"mood": BriefingMood.WINBACK})

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.WINBACK_BACKOFF

        world.voice.assert_not_awaited()
        world.nothing_sent()

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_brief_already_delivered_today_is_not_sent_again(
        self, world: World, kind: BriefingKind
    ) -> None:
        await run_brief(USER, kind)
        sent = world.today(kind)
        for seam in (world.voice, world.notify, world.post):
            seam.reset_mock()

        assert await run_brief(USER, kind) is BriefingRunOutcome.ALREADY_DELIVERED

        world.voice.assert_not_awaited()
        world.notify.assert_not_awaited()
        world.post.assert_not_awaited()
        assert world.today(kind) == sent

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_run_started_while_one_is_writing_the_same_brief_is_skipped(
        self, world: World, kind: BriefingKind
    ) -> None:
        """Two fires for one brief both passed the delivered check and stored over each other."""
        writing, finish = asyncio.Event(), asyncio.Event()
        speaks = world.voice.side_effect

        async def held_voice(*args: object, **kwargs: object) -> object:
            if not writing.is_set():
                writing.set()
                await finish.wait()
            return await speaks(*args, **kwargs)

        world.voice.side_effect = held_voice
        first = asyncio.ensure_future(run_brief(USER, kind))
        await writing.wait()

        second = await run_brief(USER, kind)
        finish.set()

        assert second is BriefingRunOutcome.ALREADY_RUNNING
        assert await first is BriefingRunOutcome.SENT
        world.voice.assert_awaited_once()

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_run_locks_its_own_brief_and_never_waits_for_the_lock(
        self, world: World, kind: BriefingKind
    ) -> None:
        await run_brief(USER, kind)

        assert world.locks == [
            (
                f"{BRIEF_RUN_LOCK_PREFIX}{USER}:{kind}",
                {
                    "lease_seconds": BRIEF_RUN_LOCK_LEASE_SECONDS,
                    "acquire_timeout_seconds": 0,
                    "renew_seconds": BRIEF_RUN_LOCK_RENEW_SECONDS,
                    "max_hold_seconds": BRIEF_RUN_LOCK_MAX_HOLD_SECONDS,
                },
            )
        ]

    async def test_a_failed_delivery_records_no_channels_and_clears_nothing(
        self, world: World
    ) -> None:
        world.held = [held("h1", "Paper digest", DIGEST_REPORT)]
        world.notify.side_effect = RuntimeError("orchestrator down")

        with pytest.raises(RuntimeError):
            await run_brief(USER, BriefingKind.DAILY)

        assert world.today() is not None
        assert all(b.delivered_channels == [] for b in world.briefs.values())
        world.post.assert_not_awaited()
        assert (world.pending.consumed, [h.id for h in world.held]) == ([], ["h1"])

    async def test_a_run_that_died_mid_delivery_is_finished_not_resent_or_dropped(
        self, world: World
    ) -> None:
        """A killed worker's retry once saw no delivered channel, rebuilt the brief and sent it twice."""
        world.held = [held("h1", "Paper digest", DIGEST_REPORT)]
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(USER, BriefingKind.DAILY)
        assert world.pending.consumed == []
        world.post.side_effect = None

        async with captured_wide_event() as event:
            outcome = await run_brief(USER, BriefingKind.DAILY)

        assert outcome is BriefingRunOutcome.SENT
        assert {k: event["briefing"][k] for k in ("kind", "resumed", "channels", "pushed")} == {
            "kind": "daily",
            "resumed": True,
            "channels": [*ORCHESTRATED, "telegram"],
            "pushed": True,
        }
        world.render.assert_awaited_once()
        world.notify.assert_awaited_once()
        world.brief_message.assert_awaited_once()
        # The failed run posted, then its rerun resumed and posted again; then this run.
        assert world.post.await_count == 3
        assert (world.pending.consumed, world.held) == ([["h1"]], [])
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]
        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.ALREADY_DELIVERED

    async def test_a_render_whose_browser_died_is_run_again_and_delivered(
        self, world: World
    ) -> None:
        """Sim 12-03: the render's driver died, the brief stayed stored undelivered and nothing retried it."""
        world.render.side_effect = [
            TargetClosedError("Target page, context or browser has been closed"),
            RENDERED,
        ]

        async with captured_wide_event() as event:
            assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        [rerun] = [w for w in event["warnings"] if w["msg"] == "briefing.rerun_undelivered"]
        assert (rerun["error"], rerun["error_type"]) == (
            "Target page, context or browser has been closed",
            "TargetClosedError",
        )
        assert world.render.await_count == 2
        world.notify.assert_awaited_once()
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]

    async def test_a_run_that_failed_after_its_brief_was_delivered_is_not_run_again(
        self, world: World
    ) -> None:
        world.capture.side_effect = RuntimeError("analytics down")

        with pytest.raises(RuntimeError, match="analytics down"):
            await run_brief(USER, BriefingKind.DAILY)

        world.notify.assert_awaited_once()
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]

    async def test_a_run_that_failed_before_storing_a_brief_is_not_run_again(
        self, world: World
    ) -> None:
        world.voice.side_effect = RuntimeError("model down")

        with pytest.raises(RuntimeError, match="model down"):
            await run_brief(USER, BriefingKind.DAILY)

        world.voice.assert_awaited_once()
        assert world.today() is None

    async def test_a_resumed_goodbye_still_puts_the_loop_to_sleep_and_spends_its_draw(
        self, world: World
    ) -> None:
        """A goodbye whose delivery died was finished on the retry, but the loop never went dormant."""
        idle_day(world, IDLE_DORMANT_DAYS)
        pinned = world.bags[BriefingBag.EDITION_FAMILY]
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(USER, BriefingKind.DAILY)
        assert ladder_state(world.state).wound_down_since is None
        assert world.bags[BriefingBag.EDITION_FAMILY] == pinned
        world.post.side_effect = None

        assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        ladder = ladder_state(world.state)
        assert (ladder.wound_down_since, ladder.goal_asked_at) == (NOW, NOW)
        assert world.bags[BriefingBag.EDITION_FAMILY].index == pinned.index + 1

    async def test_a_resumed_brief_marks_what_it_placed_shown(self, world: World) -> None:
        world.scouts = scouted(LOGIN)
        world.post.side_effect = RuntimeError("worker killed")
        with pytest.raises(RuntimeError, match="worker killed"):
            await run_brief(USER, BriefingKind.DAILY)
        assert [r.times_shown for r in world.memory] == [0]
        world.post.side_effect = None

        await run_brief(USER, BriefingKind.DAILY)

        [login] = world.memory
        assert (login.external_id, login.times_shown, login.last_shown) == (
            LOGIN.external_id,
            1,
            NOW,
        )

    async def test_an_edition_reaches_the_chat_app_as_a_routine_photo_and_the_conversation_as_its_card(
        self, world: World
    ) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        message = world.stored().message
        post = world.post.await_args.kwargs
        assert set(post) == {
            "user",
            "channel",
            "message",
        }
        assert post["user"] == build_user_context(world.user, auth_provider=None)
        assert (post["channel"], post["message"].origin, post["message"].message_class) == (
            CHAT,
            "daily brief",
            ProactiveMessageClass.ROUTINE,
        )
        assert split_message_bubbles(post["message"].text) == [
            "Your morning, sorted",
            f"{message}\n\nFull brief: {BRIEF_LINK}",
        ]
        assert post["message"].image_url.startswith(CHAT_EDITION_URL)
        user_id, briefing_id, text, card = world.brief_message.await_args.args
        assert (user_id, briefing_id, text, card.briefing_id) == (USER, BRIEF_ID, message, BRIEF_ID)
        redirect = world.notify.await_args.args[0].content.actions[0].config.redirect
        assert redirect.url == f"/brief/{BRIEF_ID}"
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]

    async def test_a_note_reaches_the_chat_app_as_its_plain_message(self, world: World) -> None:
        quiet_day(world)

        await run_brief(USER, BriefingKind.DAILY)

        message = world.stored().message
        post = world.post.await_args.kwargs
        assert (post["message"].text, post["message"].image_url, post["message"].origin) == (
            message,
            None,
            "daily brief",
        )
        world.brief_message.assert_awaited_once_with(USER, BRIEF_ID, message, None)
        assert world.delivered_to() == [*ORCHESTRATED, "telegram"]

    async def test_each_delivery_step_is_recorded_once_it_succeeds(self, world: World) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        brief = world.today()
        assert brief is not None and brief.delivery is not None
        assert brief.delivery.done == [
            DeliveryStep.NOTIFICATION,
            DeliveryStep.CONVERSATION,
            DeliveryStep.CHAT,
        ]

    @pytest.mark.parametrize("result", [OutboundResult.SKIPPED, OutboundResult.FAILED])
    async def test_a_chat_post_that_did_not_publish_records_no_platform(
        self, world: World, result: OutboundResult
    ) -> None:
        world.post.return_value = result

        await run_brief(USER, BriefingKind.DAILY)

        world.post.assert_awaited_once()
        assert world.delivered_to() == ORCHESTRATED

    async def test_an_unsent_email_is_reported_with_every_channels_status(
        self, world: World
    ) -> None:
        world.notify.return_value = notified(
            delivered("inapp"),
            ChannelDeliveryStatus(channel_type="email", status=NotificationStatus.FAILED),
        )

        async with captured_wide_event() as event:
            await run_brief(USER, BriefingKind.DAILY)

        [warning] = [w for w in event["warnings"] if w["msg"] == "briefing.email_not_sent"]
        assert warning["statuses"] == {"inapp": "delivered", "email": "failed"}

    async def test_a_brief_that_asked_for_no_email_reports_none_unsent(self, world: World) -> None:
        world.user.email = None
        world.notify.return_value = notified(delivered("inapp"))

        async with captured_wide_event() as event:
            await run_brief(USER, BriefingKind.DAILY)

        assert [c.channel_type for c in world.notify.await_args.args[0].channels] == ["inapp"]
        assert "briefing.email_not_sent" not in [w["msg"] for w in event.get("warnings", [])]

    async def test_a_reader_who_turned_email_off_is_notified_in_app_only(
        self, world: World
    ) -> None:
        world.user.notification_channel_prefs = {"email": False}
        world.notify.return_value = notified(delivered("inapp"))

        await run_brief(USER, BriefingKind.DAILY)

        assert [c.channel_type for c in world.notify.await_args.args[0].channels] == ["inapp"]

    async def test_the_notification_is_keyed_by_its_brief_and_opens_it_in_place(
        self, world: World
    ) -> None:
        await run_brief(USER, BriefingKind.DAILY)

        request = world.notify.await_args.args[0]
        assert (request.id, request.priority) == (
            notification_id(USER, "brief", BRIEF_ID),
            BRIEF_NOTIFICATION_PRIORITY,
        )
        [action] = request.content.actions
        assert (action.style, action.config.redirect) == (
            ActionStyle.PRIMARY,
            RedirectConfig(
                url=f"/brief/{BRIEF_ID}", open_in_new_tab=False, close_notification=True
            ),
        )

    async def test_a_resumed_delivery_reports_the_channels_earlier_steps_reached(
        self, world: World
    ) -> None:
        stored = stored_brief(DATE, BriefForm.QUIET_NOTE, message="Gym").model_copy(
            update={
                "delivered_channels": ["telegram"],
                "delivery": BriefDelivery(
                    push=True,
                    notification_kind=NotificationKind.BRIEFING_NOTE,
                    done=[DeliveryStep.CHAT],
                ),
            }
        )
        world.briefs[stored.id] = stored

        async with captured_wide_event() as event:
            assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert event["briefing"]["channels"] == ["telegram", *ORCHESTRATED]

    async def test_a_brief_stored_without_a_delivery_plan_is_not_delivered(
        self, world: World
    ) -> None:
        stored = stored_brief(DATE, BriefForm.EDITION, message="Gym").model_copy(
            update={"delivery": None}
        )

        with pytest.raises(
            ValueError, match=f"^brief {stored.id} was stored without a delivery plan$"
        ):
            await delivery.deliver_brief(world.user, stored)

        world.notify.assert_not_awaited()

    async def test_resuming_an_edition_brief_stored_without_its_edition_fails_loud(
        self, world: World
    ) -> None:
        stored = stored_brief(DATE, BriefForm.EDITION, message="Gym").model_copy(
            update={
                "link": BRIEF_LINK,
                "delivery": BriefDelivery(
                    push=True,
                    notification_kind=NotificationKind.BRIEFING_DAILY,
                    done=[DeliveryStep.CHAT],
                ),
            }
        )
        world.briefs[stored.id] = stored

        with pytest.raises(ValueError, match=f"^briefing_daily brief {stored.id} was stored"):
            await run_brief(USER, BriefingKind.DAILY)

        world.notify.assert_not_awaited()

    async def test_a_stalled_voice_fails_the_run_instead_of_hanging(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def stall(*_: object, **__: object) -> None:
            await asyncio.Event().wait()

        world.voice.side_effect = stall
        monkeypatch.setitem(
            KIND_SPECS,
            BriefingKind.WEEKLY,
            replace(KIND_SPECS[BriefingKind.WEEKLY], voice_timeout_seconds=0),
        )

        run = asyncio.ensure_future(run_brief(USER, BriefingKind.WEEKLY))
        try:
            done, _ = await asyncio.wait({run}, timeout=5)
            assert run in done
            assert isinstance(run.exception(), TimeoutError)
        finally:
            run.cancel()
        world.nothing_sent()
