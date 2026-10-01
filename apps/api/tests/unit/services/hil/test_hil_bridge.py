"""Attacks on the approval bridge (app/services/hil/bridge.py).

The bridge is what the user actually sees, and what stops them being asked twice:

* **Publish exactly once.** The gate re-enters this on every resume replay, so the card is
  gated on whether the upsert really created the record. Publish unconditionally and the
  user collects a new card for the same action on every replay.
* **Deliver twice, to two places.** Every frame goes to the SSE stream (live and reload)
  AND the session's tool-event collector (persistence). Drop either and the card is
  missing from one of them — invisible after a refresh, or absent from the saved turn.
* **Remember a decline by its ARGUMENTS.** The memory is keyed on the exact call. Too loose
  and a corrected retry ("send it to Alice instead") is auto-denied without asking; too
  strict and a verbatim retry re-prompts the user for something they just refused.
"""

import asyncio
from collections.abc import Iterator
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    HIL_SUMMARY_MAX_ARG_CHARS,
    HIL_SUMMARY_MAX_ARGS,
)
from app.constants.log_tags import LogTag
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalStatus, LedgerState
from app.services.analytics_service import AnalyticsEvents
from app.services.hil.bridge import (
    ApprovalOutcome,
    build_summary,
    flush_held_approval_cards,
    publish_approval_request,
    publish_decision,
    publish_ledger_request,
    recall_declined_call,
    remember_declined_call,
    settle_session_approval_frame,
    sync_conversation_approval_flag,
)
from app.services.hil.utils import GatedCall

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_record

MODULE = "app.services.hil.bridge"

TOOL_CALL = GatedCall(id="call-1", name="send_email", args={"to": "bob@example.com"})


@pytest.fixture
def bridge():
    """Patch the publish side: the store's verdict, the SSE stream, the session collector, and the notifier."""
    session = MagicMock(tool_events=[])
    with (
        patch(f"{MODULE}.log") as log,
        patch(f"{MODULE}.upsert_pending_approval", new=AsyncMock(return_value=True)) as upsert,
        patch(f"{MODULE}.stream_manager") as stream,
        patch(f"{MODULE}.get_session", return_value=session) as get_session,
        patch(f"{MODULE}.notify_approval_pending", new=AsyncMock()) as notify,
        patch(f"{MODULE}.conversation_repository") as conversations,
    ):
        stream.publish_chunk = AsyncMock()
        conversations.set_message_approval_status = AsyncMock()
        yield {
            "upsert": upsert,
            "stream": stream,
            "session": session,
            "get_session": get_session,
            "notify": notify,
            "conversations": conversations,
            "log": log,
        }


async def publish(bridge: dict) -> None:
    await publish_approval_request(
        approval_id="appr-1",
        stream_id=STREAM_ID,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        tool_call=TOOL_CALL,
        summary="Send email — to: bob@example.com",
        integration_name="Gmail",
    )
    await asyncio.sleep(0)  # let the fire-and-forget notify task start


def published_frame(bridge: dict) -> dict[str, Any]:
    raw = bridge["stream"].publish_chunk.await_args.args[1]
    assert raw.startswith("data: ") and raw.endswith("\n\n")
    return json.loads(raw[len("data: ") :])["tool_data"]


class TestPublishExactlyOnce:
    async def test_a_new_approval_is_surfaced_and_wakes_the_user(self, bridge: dict) -> None:
        bridge["upsert"].return_value = True

        await publish(bridge)

        bridge["stream"].publish_chunk.assert_awaited_once()
        bridge["notify"].assert_awaited_once()

    async def test_a_resume_replay_publishes_nothing_and_wakes_nobody(self, bridge: dict) -> None:
        # The node re-runs from the top on every resume. Re-publishing would stack a
        # duplicate card per replay and re-push a notification for a card already answered.
        bridge["upsert"].return_value = False

        await publish(bridge)

        bridge["stream"].publish_chunk.assert_not_awaited()
        bridge["notify"].assert_not_awaited()
        assert bridge["session"].tool_events == []

    async def test_a_new_pause_is_counted_exactly_once(self, bridge: dict) -> None:
        # hil_pause_total counts genuine pauses; the pause is born here (gated on
        # `created`), not at the later decision.
        from prometheus_client import REGISTRY

        bridge["upsert"].return_value = True
        before = REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0

        await publish(bridge)

        assert (REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0) == before + 1

    async def test_a_resume_replay_is_not_counted_as_a_pause(self, bridge: dict) -> None:
        from prometheus_client import REGISTRY

        bridge["upsert"].return_value = False
        before = REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0

        await publish(bridge)

        assert (REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0) == before


class TestDualDelivery:
    async def test_the_card_reaches_both_the_stream_and_the_persisted_turn(
        self, bridge: dict
    ) -> None:
        # The gate only fires inside the detached executor, where get_stream_writer() is
        # unavailable — this dual write keyed on stream_id is what makes the card work at
        # every nesting depth. One without the other means a card that vanishes on reload.
        await publish(bridge)

        bridge["stream"].publish_chunk.assert_awaited_once()
        assert len(bridge["session"].tool_events) == 1
        assert bridge["session"].tool_events[0]["tool_data"]["data"]["approval_id"] == "appr-1"

    async def test_a_missing_session_still_reaches_the_live_stream(self, bridge: dict) -> None:
        bridge["get_session"].return_value = None

        await publish(bridge)

        bridge["stream"].publish_chunk.assert_awaited_once()

    async def test_the_frame_carries_what_the_client_needs_to_decide(self, bridge: dict) -> None:
        await publish(bridge)

        data = published_frame(bridge)["data"]
        assert data["approval_id"] == "appr-1"
        assert data["status"] == "pending"
        assert data["gated_tool_name"] == "send_email"
        assert data["tool_call_id"] == "call-1"
        assert data["timeout_seconds"] > 0


class TestTheOutcomeSettlesTheCard:
    """The card is live UI, published pending BEFORE the run parks on interrupt().

    When the decision lands and the run resumes, the same card has to be republished in
    its settled state. Skip it and the action really happens — or is really refused —
    while the user goes on looking at an open Approve/Deny prompt for it, with no way to
    tell the request through from one still waiting on them. The resumed run publishes to
    a NEW stream, which is why this is a fresh publish rather than an edit in place.
    """

    async def settle(self, outcome: ApprovalOutcome) -> None:
        record = make_record(
            approval_id="appr-1",
            tool_name=TOOL_CALL.name,
            tool_call_id=TOOL_CALL.id,
            args=TOOL_CALL.args,
            summary="Send email — to: bob@example.com",
            integration_name="Gmail",
        )
        # STREAM_ID explicitly, never record.stream_id: a resumed run publishes to a
        # NEW stream, and the card has to settle where the user is now watching.
        await publish_decision(
            record, outcome.status, stream_id=STREAM_ID, feedback=outcome.feedback
        )

    async def test_an_approval_settles_the_card(self, bridge: dict) -> None:
        await self.settle(ApprovalOutcome(status=HILApprovalStatus.APPROVED))

        data = published_frame(bridge)["data"]
        assert data["status"] == "approved"
        assert data["approval_id"] == "appr-1", "the settled card must replace the right one"

    async def test_a_denial_settles_the_card_and_shows_why(self, bridge: dict) -> None:
        await self.settle(
            ApprovalOutcome(status=HILApprovalStatus.DENIED, feedback="wrong recipient")
        )

        data = published_frame(bridge)["data"]
        assert data["status"] == "denied"
        assert data["feedback"] == "wrong recipient"

    async def test_the_settled_card_is_persisted_as_well_as_streamed(self, bridge: dict) -> None:
        # Same dual-delivery contract as the pending card: stream-only means the card
        # reverts to "pending" on reload, which is the confusing state all over again.
        await self.settle(ApprovalOutcome(status=HILApprovalStatus.APPROVED))

        bridge["stream"].publish_chunk.assert_awaited_once()
        assert len(bridge["session"].tool_events) == 1
        assert bridge["session"].tool_events[0]["tool_data"]["data"]["status"] == "approved"


class TestTheDecisionSettlesThePersistedFrame:
    """publish_decision also settles the status on the stored message, not just the live frame.

    A run can pause again on a later gate before final delivery reconciles, so without this a
    revisit re-renders an Approve/Deny prompt for a decision already made. This write repairs
    the turn the user scrolls back to; the settled-card write above replaces the live frame
    they are watching now.
    """

    async def settle(self, status: HILApprovalStatus = HILApprovalStatus.APPROVED) -> None:
        record = make_record(
            approval_id="appr-1",
            tool_name=TOOL_CALL.name,
            tool_call_id=TOOL_CALL.id,
            args=TOOL_CALL.args,
            summary="Send email — to: bob@example.com",
            integration_name="Gmail",
        )
        await publish_decision(record, status, stream_id=STREAM_ID, feedback=None)

    async def test_the_stored_card_is_settled_against_the_right_message(self, bridge: dict) -> None:
        await self.settle(HILApprovalStatus.APPROVED)

        bridge["conversations"].set_message_approval_status.assert_awaited_once_with(
            CONVERSATION_ID,
            user_id=USER_ID,
            approval_id="appr-1",
            status="approved",
        )

    async def test_a_denial_is_stored_as_a_denial(self, bridge: dict) -> None:
        await self.settle(HILApprovalStatus.DENIED)

        assert (
            bridge["conversations"].set_message_approval_status.await_args.kwargs["status"]
            == "denied"
        )

    async def test_a_failed_write_never_costs_the_user_their_decision(self, bridge: dict) -> None:
        # The caller is the gate, which fails CLOSED — an escaping write error would
        # turn a cosmetic redraw failure into a denial of what the user just chose.
        bridge["conversations"].set_message_approval_status.side_effect = RuntimeError("mongo down")

        await self.settle(HILApprovalStatus.APPROVED)

        bridge["stream"].publish_chunk.assert_awaited_once()
        assert bridge["session"].tool_events[0]["tool_data"]["data"]["status"] == "approved"

    async def test_a_failed_write_is_reported_rather_than_swallowed(self, bridge: dict) -> None:
        bridge["conversations"].set_message_approval_status.side_effect = RuntimeError("mongo down")

        await self.settle(HILApprovalStatus.APPROVED)

        # The whole call is the contract: log.error appends its message AND its
        # kwargs to the wide event's errors[], and that entry is all an operator
        # has to tell WHICH approval silently kept its pending card.
        bridge["log"].error.assert_called_once_with(
            f"{LogTag.HIL} Could not settle persisted approval frame; delivery will reconcile",
            approval_id="appr-1",
            error="mongo down",
            error_type="RuntimeError",
        )


class TestDeclineMemory:
    """Keyed on stream, tool and arguments: too loose auto-denies a correction, too strict re-asks a refusal."""

    @pytest.fixture(autouse=True)
    def redis(self):
        store: dict[str, Any] = {}

        async def _set(key: str, value: Any, ttl: int | None = None) -> None:
            store[key] = value

        async def _get(key: str) -> Any:
            return store.get(key)

        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = MagicMock()
            cache.set = AsyncMock(side_effect=_set)
            cache.get = AsyncMock(side_effect=_get)
            yield cache

    async def test_the_same_call_is_recalled_with_the_users_own_words(self) -> None:
        args = {"to": "bob@example.com", "subject": "deck"}
        await remember_declined_call(STREAM_ID, "send_email", args, "wrong person")

        outcome = await recall_declined_call(STREAM_ID, "send_email", args)

        assert outcome is not None
        assert outcome.status == "denied"
        assert outcome.feedback == "wrong person"

    async def test_a_corrected_retry_is_not_auto_denied(self) -> None:
        # THE reason the key includes the arguments: "send it to Alice instead" is a
        # DIFFERENT call. Auto-denying it would make the correction impossible to carry out.
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call(STREAM_ID, "send_email", {"to": "alice@example.com"}) is None
        )

    async def test_the_same_arguments_in_a_different_order_are_the_same_call(self) -> None:
        # Dict ordering is an artefact of how the model emitted the JSON, not a difference
        # in what is being done. Keying on it would re-prompt for an identical retry.
        await remember_declined_call(
            STREAM_ID, "send_email", {"to": "bob@example.com", "subject": "deck"}, "no"
        )

        outcome = await recall_declined_call(
            STREAM_ID, "send_email", {"subject": "deck", "to": "bob@example.com"}
        )

        assert outcome is not None

    async def test_another_tool_with_the_same_arguments_is_a_different_call(self) -> None:
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call(STREAM_ID, "delete_email", {"to": "bob@example.com"}) is None
        )

    async def test_a_later_turn_is_not_bound_by_an_earlier_decline(self) -> None:
        # The memory is per-stream (per turn) on purpose: a genuinely new request later
        # must be able to ask again rather than inherit a refusal.
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        assert (
            await recall_declined_call("stream-2", "send_email", {"to": "bob@example.com"}) is None
        )

    async def test_a_call_never_declined_is_not_recalled(self) -> None:
        assert (
            await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}) is None
        )

    async def test_an_auto_refusal_round_trips_its_provenance(self) -> None:
        # The retry message differs ("auto declined" vs "the user declined"), so
        # the provenance must survive the Redis round trip.
        await remember_declined_call(
            STREAM_ID, "send_email", {"to": "bob@example.com"}, "stop spamming", auto=True
        )

        outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"})

        assert outcome is not None
        assert outcome.auto is True
        assert outcome.feedback == "stop spamming"

    async def test_a_user_decline_still_reads_as_user_made(self) -> None:
        await remember_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"}, "no")

        outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob@example.com"})

        assert outcome is not None
        assert outcome.auto is False

    async def test_unserializable_arguments_do_not_crash_the_gate(self) -> None:
        # Tool args come from an LLM and are only loosely typed. A key derivation that
        # raises here would fail the gate closed on every call carrying an odd value.
        args = {"when": object()}
        await remember_declined_call(STREAM_ID, "send_email", args, "no")

        assert await recall_declined_call(STREAM_ID, "send_email", args) is not None


class TestSummary:
    """The one line the user reads before approving, built deterministically with no LLM on the hot path."""

    def test_the_tool_and_integration_are_both_named(self) -> None:
        summary = build_summary("send_email", {}, "Gmail")

        assert "Send email" in summary
        assert "Gmail" in summary

    def test_scalar_arguments_are_shown_so_the_user_knows_what_they_approve(self) -> None:
        summary = build_summary("send_email", {"to": "bob@example.com"}, None)

        assert "to" in summary
        assert "bob@example.com" in summary

    def test_a_long_value_is_clipped_rather_than_flooding_the_card(self) -> None:
        summary = build_summary("send_email", {"body": "x" * 500}, None)

        assert len(summary) < 200
        assert "x" * (HIL_SUMMARY_MAX_ARG_CHARS + 1) not in summary

    def test_only_a_few_arguments_are_shown(self) -> None:
        args = {f"field_{i}": f"value_{i}" for i in range(10)}

        summary = build_summary("send_email", args, None)

        shown = [name for name in args if name in summary]
        assert len(shown) == HIL_SUMMARY_MAX_ARGS

    def test_a_nested_argument_is_skipped_rather_than_dumped_into_the_card(self) -> None:
        # A raw dict/list in a one-line summary is unreadable, and an attachment payload
        # could be enormous.
        summary = build_summary(
            "send_email", {"attachments": [{"name": "secret.pdf"}], "to": "bob@example.com"}, None
        )

        assert "secret.pdf" not in summary
        assert "bob@example.com" in summary

    def test_a_call_with_no_arguments_still_reads_as_a_sentence(self) -> None:
        assert build_summary("delete_everything", {}, None) == "Delete everything"


class TestCardShownEvent:
    async def test_register_emits_card_shown_with_user_id(self, bridge: dict) -> None:
        """The funnel's first event must attribute to the row's user — the bridge carries no request context, so an inferred id is unavailable and an anonymous capture would strand it."""
        with patch(f"{MODULE}.capture_event") as capture:
            await publish_ledger_request(
                approval_id="ap_1",
                stream_id=STREAM_ID,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                tool_call=TOOL_CALL,
                summary="Send it",
                integration_name="Gmail",
            )

        capture.assert_called_once_with(
            USER_ID,
            AnalyticsEvents.HIL_CARD_SHOWN,
            {
                "approval_id": "ap_1",
                "tool_name": "send_email",
                "ledger_version": 0,
                "background": False,
            },
        )

    async def test_background_register_marks_background(self, bridge: dict) -> None:
        with patch(f"{MODULE}.capture_event") as capture:
            await publish_ledger_request(
                approval_id="ap_1",
                stream_id=STREAM_ID,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                tool_call=TOOL_CALL,
                summary="Send it",
                integration_name="Gmail",
                live=False,
            )

        assert capture.call_args.args[2]["background"] is True


class TestBackgroundFlagSync:
    async def test_publish_with_owner_marks_the_conversation(self, bridge: dict) -> None:
        with (
            patch(f"{MODULE}.capture_event"),
            patch(
                f"{MODULE}.conversation_repository.mark_background_with_live_approval",
                new=AsyncMock(return_value=True),
            ) as mark,
        ):
            await publish_ledger_request(
                approval_id="ap_1",
                stream_id=STREAM_ID,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                tool_call=TOOL_CALL,
                summary="Send it",
                integration_name="Gmail",
                owner_run_type="todo",
                owner_id="todo-9",
            )

        mark.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID)

    async def test_publish_without_owner_touches_no_flag(self, bridge: dict) -> None:
        with (
            patch(f"{MODULE}.capture_event"),
            patch(
                f"{MODULE}.conversation_repository.mark_background_with_live_approval",
                new=AsyncMock(),
            ) as mark,
        ):
            await publish_ledger_request(
                approval_id="ap_1",
                stream_id=STREAM_ID,
                user_id=USER_ID,
                conversation_id=CONVERSATION_ID,
                tool_call=TOOL_CALL,
                summary="Send it",
                integration_name="Gmail",
            )

        mark.assert_not_called()

    async def test_sync_sets_flag_from_live_rows(self) -> None:
        from app.models.hil_models import LedgerState
        from app.services.hil.bridge import sync_conversation_approval_flag

        live = MagicMock()
        live.user_id = USER_ID
        live.state = LedgerState.PENDING
        dead = MagicMock()
        dead.user_id = USER_ID
        dead.state = LedgerState.DENIED
        foreign = MagicMock()
        foreign.user_id = "someone-else"
        foreign.state = LedgerState.PENDING
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(return_value=[live, dead, foreign]),
            ),
            patch(
                f"{MODULE}.conversation_repository.refresh_live_approval_flag",
                new=AsyncMock(),
            ) as refresh,
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)

        refresh.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID, live=True)

    async def test_sync_clears_flag_when_nothing_live(self) -> None:
        from app.services.hil.bridge import sync_conversation_approval_flag

        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                f"{MODULE}.conversation_repository.refresh_live_approval_flag",
                new=AsyncMock(),
            ) as refresh,
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)

        refresh.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID, live=False)

    async def test_approved_ticket_keeps_no_sidebar_row(self) -> None:
        """Decided means nothing left to tap: the sidebar flag is PENDING-only."""
        from app.models.hil_models import LedgerState
        from app.services.hil.bridge import sync_conversation_approval_flag

        approved = MagicMock()
        approved.user_id = USER_ID
        approved.state = LedgerState.APPROVED
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(return_value=[approved]),
            ),
            patch(
                f"{MODULE}.conversation_repository.refresh_live_approval_flag",
                new=AsyncMock(),
            ) as refresh,
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)

        refresh.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID, live=False)

    async def test_sync_failure_never_breaks_the_gate(self) -> None:
        from app.services.hil.bridge import sync_conversation_approval_flag

        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{MODULE}.log"),
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)


async def publish_ledger(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "approval_id": "ap_1",
        "stream_id": STREAM_ID,
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "tool_call": TOOL_CALL,
        "summary": "Send it",
        "integration_name": "Gmail",
        "live": False,
    }
    with patch(f"{MODULE}.capture_event"):
        await publish_ledger_request(**{**kwargs, **overrides})
    await asyncio.sleep(0)  # let the fire-and-forget notify task start


class TestLedgerCardPublish:
    async def test_the_ledger_card_carries_the_why_and_a_fresh_version(self, bridge: dict) -> None:
        await publish_ledger(rationale="user asked to send it", auto_reason="judge said ask")

        bridge["stream"].publish_chunk.assert_awaited_once()
        assert bridge["stream"].publish_chunk.await_args.args[0] == STREAM_ID
        data = published_frame(bridge)["data"]
        assert data["integration_name"] == "Gmail"
        assert data["rationale"] == "user asked to send it"
        assert data["auto_reason"] == "judge said ask"
        assert data["age_seconds"] == 0
        assert data["ledger_version"] == 0

    async def test_an_unheld_card_wakes_the_user_about_the_right_approval(
        self, bridge: dict
    ) -> None:
        await publish_ledger()

        bridge["notify"].assert_awaited_once_with(USER_ID, CONVERSATION_ID, "ap_1", "Send it")

    async def test_the_wide_event_names_the_approval_tool_and_stream(self, bridge: dict) -> None:
        await publish_ledger()

        bridge["log"].set.assert_any_call(
            hil={"approval_id": "ap_1", "tool": "send_email", "stream_id": STREAM_ID}
        )

    @pytest.mark.parametrize(
        "owner", [{"owner_run_type": "todo"}, {"owner_id": "todo-9"}], ids=["type", "id"]
    )
    async def test_half_an_owner_never_marks_the_conversation(
        self, bridge: dict, owner: dict[str, str]
    ) -> None:
        bridge["conversations"].mark_background_with_live_approval = AsyncMock()

        await publish_ledger(**owner)

        bridge["conversations"].mark_background_with_live_approval.assert_not_awaited()


class TestApprovalFlagSyncScope:
    async def test_only_the_users_own_pending_rows_raise_the_flag(self) -> None:
        foreign = ApprovalLedgerDocument(
            approval_id="ap_x",
            conversation_id=CONVERSATION_ID,
            user_id="someone-else",
            fingerprint="fp",
            tool_name="send_email",
        )
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(return_value=[foreign]),
            ) as list_open,
            patch(
                f"{MODULE}.conversation_repository.refresh_live_approval_flag", new=AsyncMock()
            ) as refresh,
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)

        list_open.assert_awaited_once_with(CONVERSATION_ID)
        refresh.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID, live=False)

    async def test_a_failed_sync_is_reported_on_the_wide_event(self) -> None:
        with (
            patch(
                f"{MODULE}.approval_ledger_repository.list_open",
                new=AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await sync_conversation_approval_flag(CONVERSATION_ID, USER_ID)

        log.warning.assert_called_once()
        assert "approval-flag sync failed" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {
            "conversation_id": CONVERSATION_ID,
            "error": "mongo down",
            "error_type": "RuntimeError",
        }


class TestDeclineMemoryLegacyRecord:
    async def test_a_record_without_provenance_reads_as_the_users_own_decline(self) -> None:
        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = MagicMock()
            cache.get = AsyncMock(return_value={"feedback": "no"})

            outcome = await recall_declined_call(STREAM_ID, "send_email", {"to": "bob"})

        assert outcome is not None
        assert outcome.auto is False
        assert outcome.feedback == "no"


def _card_frame(approval_id: str, *, held: bool = False, **data: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "tool_data": {
            "tool_name": APPROVAL_REQUEST_TOOL_NAME,
            "data": {"approval_id": approval_id, "status": "pending", **data},
        }
    }
    if held:
        frame["_held_approval"] = True
    return frame


def _ledger_row(
    approval_id: str, state: LedgerState = LedgerState.PENDING
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="send_email",
        summary=f"summary {approval_id}",
        state=state,
    )


class TestSettleSessionApprovalFrame:
    """Settling flips the matching card in place and leaves every other frame exactly as it was."""

    def test_only_the_matching_card_is_settled_and_nothing_else_moves(self, bridge: dict) -> None:
        other_event = {"text": "hello"}
        other_tool = {"tool_data": {"tool_name": "web_search", "data": {"q": "x"}}}
        dataless_card = {"tool_data": {"tool_name": APPROVAL_REQUEST_TOOL_NAME}}
        other_card = _card_frame("ap_other")
        target = _card_frame("ap_1", held=True)
        events: list[object] = [other_event, other_tool, dataless_card, other_card, target]
        bridge["session"].tool_events = events

        settled = settle_session_approval_frame(STREAM_ID, "ap_1", "denied", "wrong person")

        assert settled is True
        assert bridge["session"].tool_events == [
            {"text": "hello"},
            {"tool_data": {"tool_name": "web_search", "data": {"q": "x"}}},
            {"tool_data": {"tool_name": APPROVAL_REQUEST_TOOL_NAME}},
            _card_frame("ap_other"),
            _card_frame("ap_1", held=True, status="denied", feedback="wrong person"),
        ]

    def test_settling_without_feedback_adds_no_feedback(self, bridge: dict) -> None:
        bridge["session"].tool_events = [_card_frame("ap_1")]

        assert settle_session_approval_frame(STREAM_ID, "ap_1", "approved") is True

        assert bridge["session"].tool_events == [
            {
                "tool_data": {
                    "tool_name": APPROVAL_REQUEST_TOOL_NAME,
                    "data": {"approval_id": "ap_1", "status": "approved"},
                }
            }
        ]

    def test_drop_if_unpublished_removes_a_held_card_but_settles_a_shown_one(
        self, bridge: dict
    ) -> None:
        bridge["session"].tool_events = [_card_frame("ap_1", held=True), _card_frame("ap_2")]

        dropped = settle_session_approval_frame(
            STREAM_ID, "ap_1", "revoked", drop_if_unpublished=True
        )
        settled = settle_session_approval_frame(
            STREAM_ID, "ap_2", "revoked", drop_if_unpublished=True
        )

        assert (dropped, settled) == (True, True)
        assert bridge["session"].tool_events == [_card_frame("ap_2", status="revoked")]

    def test_no_matching_card_settles_nothing(self, bridge: dict) -> None:
        bridge["session"].tool_events = [_card_frame("ap_other")]

        assert settle_session_approval_frame(STREAM_ID, "ap_1", "approved") is False
        assert bridge["session"].tool_events == [_card_frame("ap_other")]

    def test_no_session_settles_nothing(self, bridge: dict) -> None:
        bridge["get_session"].return_value = None

        assert settle_session_approval_frame(STREAM_ID, "ap_1", "approved") is False

    def test_a_settle_failure_is_reported_and_reads_as_unsettled(self, bridge: dict) -> None:
        bridge["get_session"].side_effect = RuntimeError("session store gone")

        assert settle_session_approval_frame(STREAM_ID, "ap_1", "approved") is False
        bridge["log"].warning.assert_called_once()
        assert "Approval frame settle failed" in bridge["log"].warning.call_args.args[0]
        assert bridge["log"].warning.call_args.kwargs == {
            "approval_id": "ap_1",
            "error_type": "RuntimeError",
        }


class TestFlushHeldApprovalCardsDelivery:
    """Run end publishes every still-live held card, keeps the rest of the session intact."""

    @pytest.fixture
    def rows(self) -> Iterator[dict[str, ApprovalLedgerDocument]]:
        found: dict[str, ApprovalLedgerDocument] = {}

        async def _get(approval_id: str) -> ApprovalLedgerDocument | None:
            return found.get(approval_id)

        with patch(
            f"{MODULE}.approval_ledger_repository.get_by_approval_id",
            new=AsyncMock(side_effect=_get),
        ):
            yield found

    def published(self, bridge: dict) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for call in bridge["stream"].publish_chunk.await_args_list:
            stream_id, raw = call.args
            assert raw.startswith("data: ") and raw.endswith("\n\n")
            out.append((stream_id, json.loads(raw[len("data: ") :])))
        return out

    async def test_every_live_held_card_is_published_and_unmarked(
        self, bridge: dict, rows: dict[str, ApprovalLedgerDocument]
    ) -> None:
        rows["ap_1"] = _ledger_row("ap_1")
        rows["ap_2"] = _ledger_row("ap_2", LedgerState.APPROVED)
        rows["ap_gone"] = _ledger_row("ap_gone", LedgerState.REVOKED)
        bridge["session"].tool_events = [
            "not-a-frame",
            {"text": "hello"},
            _card_frame("ap_gone", held=True),
            _card_frame("ap_1", held=True),
            _card_frame("ap_2", held=True),
        ]

        flushed = await flush_held_approval_cards(STREAM_ID)
        await asyncio.sleep(0)

        assert flushed == 2
        card_1 = {"tool_data": _card_frame("ap_1")["tool_data"]}
        card_2 = {"tool_data": _card_frame("ap_2")["tool_data"]}
        assert self.published(bridge) == [(STREAM_ID, card_1), (STREAM_ID, card_2)]
        assert bridge["session"].tool_events == ["not-a-frame", {"text": "hello"}, card_1, card_2]
        assert [c.args for c in bridge["notify"].await_args_list] == [
            (USER_ID, CONVERSATION_ID, "ap_1", "summary ap_1"),
            (USER_ID, CONVERSATION_ID, "ap_2", "summary ap_2"),
        ]

    async def test_an_unreadable_row_keeps_its_card_held_is_reported_and_the_rest_still_flush(
        self, bridge: dict
    ) -> None:
        async def _get(approval_id: str) -> ApprovalLedgerDocument:
            if approval_id == "ap_1":
                raise RuntimeError("mongo down")
            return _ledger_row(approval_id)

        bridge["session"].tool_events = [
            _card_frame("ap_1", held=True),
            _card_frame("ap_2", held=True),
        ]

        with patch(
            f"{MODULE}.approval_ledger_repository.get_by_approval_id",
            new=AsyncMock(side_effect=_get),
        ):
            assert await flush_held_approval_cards(STREAM_ID) == 1

        assert bridge["session"].tool_events == [
            _card_frame("ap_1", held=True),
            {"tool_data": _card_frame("ap_2")["tool_data"]},
        ]
        bridge["log"].error.assert_called_once()
        assert "Held card ledger read failed" in bridge["log"].error.call_args.args[0]
        assert bridge["log"].error.call_args.kwargs == {
            "approval_id": "ap_1",
            "error_type": "RuntimeError",
        }

    async def test_a_missed_publish_keeps_its_card_held_and_the_rest_still_flush(
        self, bridge: dict, rows: dict[str, ApprovalLedgerDocument]
    ) -> None:
        rows["ap_1"] = _ledger_row("ap_1")
        rows["ap_2"] = _ledger_row("ap_2")
        bridge["session"].tool_events = [
            _card_frame("ap_1", held=True),
            _card_frame("ap_2", held=True),
        ]
        bridge["stream"].publish_chunk.side_effect = [RuntimeError("redis down"), None]

        assert await flush_held_approval_cards(STREAM_ID) == 1

        assert bridge["session"].tool_events == [
            _card_frame("ap_1", held=True),
            {"tool_data": _card_frame("ap_2")["tool_data"]},
        ]
        bridge["log"].warning.assert_called_once()
        assert "Held card flush missed its stream" in bridge["log"].warning.call_args.args[0]
        assert bridge["log"].warning.call_args.kwargs == {
            "approval_id": "ap_1",
            "error_type": "RuntimeError",
        }

    async def test_a_session_failure_propagates_to_the_finalize_handler(self, bridge: dict) -> None:
        bridge["get_session"].side_effect = RuntimeError("session store gone")

        with pytest.raises(RuntimeError, match="session store gone"):
            await flush_held_approval_cards(STREAM_ID)

        bridge["stream"].publish_chunk.assert_not_awaited()
