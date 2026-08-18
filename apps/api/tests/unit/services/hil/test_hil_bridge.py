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
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import HIL_SUMMARY_MAX_ARG_CHARS, HIL_SUMMARY_MAX_ARGS
from app.constants.log_tags import LogTag
from app.models.hil_models import HILApprovalStatus
from app.services.hil.bridge import (
    ApprovalOutcome,
    build_summary,
    publish_approval_request,
    publish_decision,
    recall_declined_call,
    remember_declined_call,
)
from app.services.hil.utils import GatedCall

from .conftest import CONVERSATION_ID, STREAM_ID, USER_ID, make_record

MODULE = "app.services.hil.bridge"

TOOL_CALL = GatedCall(id="call-1", name="send_email", args={"to": "bob@example.com"})


@pytest.fixture
def bridge():
    """The publish side: the store's created/not-created verdict, the SSE stream, the
    session collector, and the out-of-band notifier."""
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
    """The card is live UI, published ``pending`` BEFORE the run parks on interrupt().

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
    """``publish_decision`` also writes the decided status straight onto the stored
    message. Final delivery reconciles too, but a run can pause again on a LATER gate
    before it ever gets there — and a revisit in that window re-renders an Approve/Deny
    prompt for something the user already decided, inviting them to decide it twice.

    Not the same write as the settled card above: that one replaces the live frame on
    the stream the user is watching now, this one repairs the turn they scroll back to.
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
    """Keyed on stream + tool + arguments. Both directions of getting that wrong are
    user-visible: too loose auto-denies a correction, too strict re-asks a refusal."""

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


class TestSummary:
    """The one line the user reads before approving. It is built deterministically — no
    LLM on the gate's hot path — so its job is to be honest and short."""

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
