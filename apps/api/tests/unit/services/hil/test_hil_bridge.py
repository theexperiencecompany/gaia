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
from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.session import RunKind
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.log_tags import LogTag
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalStatus, LedgerState
from app.models.stream_events import PendingApprovalCardData
from app.services.hil.bridge import (
    ApprovalOutcome,
    GatedApproval,
    flush_held_approval_cards,
    pending_card,
    publish_approval_request,
    publish_auto_approval,
    publish_decision,
    publish_ledger_request,
    recall_declined_call,
    remember_declined_call,
    settle_session_approval_frame,
    sync_conversation_approval_flag,
)
from app.services.hil.describe import describe_call
from app.services.hil.utils import GatedCall
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilCardShown

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_record, tools_that_always_ask

MODULE = "app.services.hil.bridge"

TOOL_CALL = GatedCall(id="call-1", name="send_email", args={"to": "bob@example.com"})
DESCRIPTION = describe_call(TOOL_CALL.name, TOOL_CALL.args, "Gmail")
SUMMARY = DESCRIPTION.headline
ASKED_AT = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)

SEPARATOR = ": "  # the colon + space between the browser-task lead-in and its task
ARG_SEPARATOR = "; "  # between a tool label and its arguments, which carry their own colons

# The stream the request was raised on, which closed when the run paused — deliberately
# NOT the stream the settled card must be published to.
PAUSED_RUN_STREAM_ID = "stream-of-the-paused-run"


@pytest.fixture
def bridge():
    """Patch the publish side: the store's verdict, the SSE stream, the session collector, and the notifier."""
    session = MagicMock(tool_events=[])
    with (
        patch(f"{MODULE}.log") as log,
        patch(
            f"{MODULE}.upsert_pending_approval", new=AsyncMock(return_value=make_record())
        ) as upsert,
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


async def publish(bridge: dict, **overrides: Any) -> None:
    await publish_approval_request(
        GatedApproval(
            approval_id="appr-1",
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            tool_call=TOOL_CALL,
            description=DESCRIPTION,
            integration_name="Gmail",
        ),
        **overrides,
    )
    await asyncio.sleep(0)  # let the fire-and-forget notify task start


def published_frame(bridge: dict) -> dict[str, Any]:
    raw = bridge["stream"].publish_chunk.await_args.args[1]
    assert raw.startswith("data: ") and raw.endswith("\n\n")
    return json.loads(raw[len("data: ") :])["tool_data"]


class TestPublishExactlyOnce:
    async def test_a_new_approval_is_surfaced_and_wakes_the_user(self, bridge: dict) -> None:
        bridge["upsert"].return_value = make_record()

        await publish(bridge)

        bridge["stream"].publish_chunk.assert_awaited_once()
        bridge["notify"].assert_awaited_once()

    async def test_the_notification_names_the_user_conversation_and_approval(
        self, bridge: dict
    ) -> None:
        # The wake-up is delivered out-of-band (push/email), so every one of these has
        # to be the real value: a wrong user notifies a stranger, a wrong conversation
        # or approval id deep-links the user to a card that isn't the one waiting.
        await publish(bridge)

        bridge["notify"].assert_awaited_once_with(USER_ID, CONVERSATION_ID, "appr-1", SUMMARY)

    async def test_the_wide_event_names_the_approval_its_tool_and_its_stream(
        self, bridge: dict
    ) -> None:
        # These three fields are all an operator has to find the turn a pending approval
        # belongs to; dropping the namespace (or renaming a key) makes the event unqueryable.
        await publish(bridge)

        bridge["log"].set.assert_called_once_with(
            hil={"approval_id": "appr-1", "tool": "send_email", "stream_id": STREAM_ID}
        )

    async def test_the_pending_card_says_why_auto_mode_stopped_to_ask(self, bridge: dict) -> None:
        # Auto mode only pauses a call it judged risky; the card is where the user reads
        # that judgement before deciding, so it must arrive with the card itself.
        await publish(bridge, auto_reason="Sends mail to someone outside your contacts")

        data = published_frame(bridge)["data"]
        assert data["status"] == "pending"
        assert data["auto_reason"] == "Sends mail to someone outside your contacts"

    async def test_a_resume_replay_publishes_nothing_and_wakes_nobody(self, bridge: dict) -> None:
        # The node re-runs from the top on every resume. Re-publishing would stack a
        # duplicate card per replay and re-push a notification for a card already answered.
        bridge["upsert"].return_value = None

        await publish(bridge)

        bridge["stream"].publish_chunk.assert_not_awaited()
        bridge["notify"].assert_not_awaited()
        assert bridge["session"].tool_events == []

    async def test_a_new_pause_is_counted_exactly_once(self, bridge: dict) -> None:
        # hil_pause_total counts genuine pauses; the pause is born here (gated on
        # `created`), not at the later decision.
        from prometheus_client import REGISTRY

        bridge["upsert"].return_value = make_record()
        before = REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0

        await publish(bridge)

        assert (REGISTRY.get_sample_value("hil_pause_total", {}) or 0.0) == before + 1

    async def test_a_resume_replay_is_not_counted_as_a_pause(self, bridge: dict) -> None:
        from prometheus_client import REGISTRY

        bridge["upsert"].return_value = None
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
        record = bridge["upsert"].return_value
        assert datetime.fromisoformat(data["asked_at"]) == record.created_at
        assert datetime.fromisoformat(data["expires_at"]) == record.expires_at
        assert data["always_asks"] is False

    @pytest.mark.regression
    async def test_a_call_that_always_asks_tells_the_client_not_to_offer_always_allow(
        self, bridge: dict
    ) -> None:
        with tools_that_always_ask("send_email"):
            await publish(bridge)

        assert published_frame(bridge)["data"]["always_asks"] is True

    async def test_a_disconnect_card_always_asks_because_of_its_arguments(
        self, bridge: dict
    ) -> None:
        disconnect = GatedCall(
            id="call-2", name="manage_linked_account", args={"action": "disconnect"}
        )
        with tools_that_always_ask():
            await publish_approval_request(
                GatedApproval(
                    approval_id="appr-2",
                    stream_id=STREAM_ID,
                    user_id=USER_ID,
                    conversation_id=CONVERSATION_ID,
                    tool_call=disconnect,
                    description=DESCRIPTION,
                    integration_name="Gmail",
                )
            )

        assert published_frame(bridge)["data"]["always_asks"] is True


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
            stream_id=PAUSED_RUN_STREAM_ID,
        )
        # STREAM_ID explicitly, never record.stream_id: a resumed run publishes to a
        # NEW stream, and the card has to settle where the user is now watching.
        await publish_decision(
            record, outcome.status, stream_id=STREAM_ID, feedback=outcome.feedback
        )

    async def test_the_card_settles_on_the_stream_the_user_is_watching_now(
        self, bridge: dict
    ) -> None:
        # The request's own stream closed when the run paused. Settling there resolves
        # the card where nobody is looking, leaving a live Approve/Deny prompt on screen.
        await self.settle(ApprovalOutcome(status=HILApprovalStatus.APPROVED))

        assert bridge["stream"].publish_chunk.await_args.args[0] == STREAM_ID

    async def test_the_settled_card_carries_the_original_calls_identity(self, bridge: dict) -> None:
        # The settled card replaces the pending one by these fields; rebuilt from the
        # stored record, so a dropped field renders a second, anonymous card instead.
        await self.settle(ApprovalOutcome(status=HILApprovalStatus.APPROVED))

        data = published_frame(bridge)["data"]
        assert data["integration_name"] == "Gmail"
        assert data["gated_tool_name"] == TOOL_CALL.name
        assert data["tool_call_id"] == TOOL_CALL.id
        assert data["summary"] == SUMMARY
        assert data["args_preview"] == TOOL_CALL.args

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

    async def test_unserializable_arguments_do_not_crash_the_gate(self) -> None:
        # Tool args come from an LLM and are only loosely typed. A key derivation that
        # raises here would fail the gate closed on every call carrying an odd value.
        args = {"when": object()}
        await remember_declined_call(STREAM_ID, "send_email", args, "no")

        assert await recall_declined_call(STREAM_ID, "send_email", args) is not None


class TestCardShownEvent:
    async def test_register_emits_card_shown_with_user_id(self, bridge: dict) -> None:
        """The funnel's first event must attribute to the row's user — the bridge carries no request context, so an inferred id is unavailable and an anonymous capture would strand it."""
        with patch(f"{MODULE}.capture") as capture:
            await publish_ledger_request(
                GatedApproval(
                    approval_id="ap_1",
                    stream_id=STREAM_ID,
                    user_id=USER_ID,
                    conversation_id=CONVERSATION_ID,
                    tool_call=TOOL_CALL,
                    description=DESCRIPTION,
                    integration_name="Gmail",
                ),
                asked_at=ASKED_AT,
            )

        capture.assert_called_once_with(
            UserId(USER_ID),
            HilCardShown(
                approval_id="ap_1", tool_name="send_email", ledger_version=0, background=False
            ),
        )

    async def test_background_register_marks_background(self, bridge: dict) -> None:
        with patch(f"{MODULE}.capture") as capture:
            await publish_ledger_request(
                GatedApproval(
                    approval_id="ap_1",
                    stream_id=STREAM_ID,
                    user_id=USER_ID,
                    conversation_id=CONVERSATION_ID,
                    tool_call=TOOL_CALL,
                    description=DESCRIPTION,
                    integration_name="Gmail",
                ),
                asked_at=ASKED_AT,
                live=False,
            )

        assert capture.call_args.args[1].background is True


class TestBackgroundFlagSync:
    async def test_publish_with_owner_marks_the_conversation(self, bridge: dict) -> None:
        with (
            patch(f"{MODULE}.capture"),
            patch(
                f"{MODULE}.conversation_repository.mark_background_with_live_approval",
                new=AsyncMock(return_value=True),
            ) as mark,
        ):
            await publish_ledger_request(
                GatedApproval(
                    approval_id="ap_1",
                    stream_id=STREAM_ID,
                    user_id=USER_ID,
                    conversation_id=CONVERSATION_ID,
                    tool_call=TOOL_CALL,
                    description=DESCRIPTION,
                    integration_name="Gmail",
                ),
                asked_at=ASKED_AT,
                owner_run_type="todo",
                owner_id="todo-9",
            )

        mark.assert_awaited_once_with(CONVERSATION_ID, user_id=USER_ID)

    async def test_publish_without_owner_touches_no_flag(self, bridge: dict) -> None:
        with (
            patch(f"{MODULE}.capture"),
            patch(
                f"{MODULE}.conversation_repository.mark_background_with_live_approval",
                new=AsyncMock(),
            ) as mark,
        ):
            await publish_ledger_request(
                GatedApproval(
                    approval_id="ap_1",
                    stream_id=STREAM_ID,
                    user_id=USER_ID,
                    conversation_id=CONVERSATION_ID,
                    tool_call=TOOL_CALL,
                    description=DESCRIPTION,
                    integration_name="Gmail",
                ),
                asked_at=ASKED_AT,
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
    approval = GatedApproval(
        approval_id="ap_1",
        stream_id=STREAM_ID,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        tool_call=TOOL_CALL,
        description=DESCRIPTION,
        integration_name="Gmail",
    )
    kwargs: dict[str, Any] = {"live": False, "asked_at": ASKED_AT}
    with patch(f"{MODULE}.capture"):
        await publish_ledger_request(approval, **{**kwargs, **overrides})
    await asyncio.sleep(0)  # let the fire-and-forget notify task start


class TestLedgerCardPublish:
    async def test_the_ledger_card_carries_when_it_was_asked_and_no_expiry(
        self, bridge: dict
    ) -> None:
        # Regression: cards carried age_seconds=0 forever, so every card read "asked just
        # now" and a bot prompt promised a 6-hour expiry that ledger approvals never have.
        await publish_ledger(auto_reason="judge said ask")

        bridge["stream"].publish_chunk.assert_awaited_once()
        assert bridge["stream"].publish_chunk.await_args.args[0] == STREAM_ID
        data = published_frame(bridge)["data"]
        assert data["integration_name"] == "Gmail"
        assert data["auto_reason"] == "judge said ask"
        assert datetime.fromisoformat(data["asked_at"]) == ASKED_AT
        assert data["expires_at"] is None
        assert "age_seconds" not in data and "timeout_seconds" not in data
        assert data["description"] == DESCRIPTION.model_dump()
        assert data["ledger_version"] == 0

    async def test_an_unheld_card_wakes_the_user_about_the_right_approval(
        self, bridge: dict
    ) -> None:
        await publish_ledger()

        bridge["notify"].assert_awaited_once_with(USER_ID, CONVERSATION_ID, "ap_1", SUMMARY)

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


class TestHeldAndAutoCards:
    async def test_a_held_live_card_is_stored_as_json_ready_for_the_drain(
        self, bridge: dict
    ) -> None:
        bridge["session"].kind = RunKind.LIVE

        await publish_ledger(live=True)

        bridge["stream"].publish_chunk.assert_not_awaited()
        (frame,) = bridge["session"].tool_events
        assert frame["_held_approval"] is True
        assert frame["tool_data"]["data"]["asked_at"] == "2026-11-10T09:30:00Z"

    async def test_an_auto_approved_receipt_says_why_auto_mode_ran_it(self, bridge: dict) -> None:
        approval = GatedApproval(
            approval_id="appr-1",
            stream_id=STREAM_ID,
            user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            tool_call=TOOL_CALL,
            description=DESCRIPTION,
            integration_name="Gmail",
        )
        with patch(f"{MODULE}.record_auto_approval", new=AsyncMock()):
            await publish_auto_approval(approval, reason="You asked to email Bob")

        data = published_frame(bridge)["data"]
        assert data["status"] == "auto_approved"
        assert data["auto_reason"] == "You asked to email Bob"


class TestPendingCard:
    """The card a bot prompt lists is rebuilt from the stored row, field for field."""

    async def test_a_ledger_row_rebuilds_its_card_with_the_account_and_version(self) -> None:
        row = ApprovalLedgerDocument(
            approval_id="ap_1",
            conversation_id=CONVERSATION_ID,
            user_id=USER_ID,
            fingerprint="fp",
            tool_name="send_email",
            args={"to": "bob@example.com"},
            account="work@example.com",
            v=3,
            created_at=ASKED_AT,
        )

        card = await pending_card(row)

        description = describe_call("send_email", row.args, None, "work@example.com")
        assert card == PendingApprovalCardData(
            approval_id="ap_1",
            tool_call_id="",
            gated_tool_name="send_email",
            integration_name=None,
            summary=description.headline,
            description=description,
            args_preview={"to": "bob@example.com"},
            feedback=None,
            auto_reason=None,
            asked_at=ASKED_AT,
            ledger_version=3,
            status="pending",
            expires_at=None,
        )
        assert "work@example.com" in card.summary

    async def test_a_barrier_record_rebuilds_its_card_with_its_expiry(self) -> None:
        record = make_record(integration_name="Gmail", created_at=ASKED_AT)

        card = await pending_card(record)

        assert card == PendingApprovalCardData(
            approval_id="appr-1",
            tool_call_id="call-1",
            gated_tool_name="send_email",
            integration_name="Gmail",
            summary=SUMMARY,
            description=DESCRIPTION,
            args_preview={"to": "bob@example.com"},
            feedback=None,
            auto_reason=None,
            asked_at=ASKED_AT,
            status="pending",
            expires_at=record.expires_at,
        )
