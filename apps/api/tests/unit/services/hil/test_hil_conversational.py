"""Attacks on the chat-reply resolver (app/services/hil/conversational.py).

This is the ONLY decision surface a text-only channel has: WhatsApp and Telegram have no
approve/deny buttons, so "yes" typed into a chat is the whole approval UI. That makes the
classifier a security boundary, and the attacks that matter are the ones that turn an
ambiguous or broken reply into an action:

* a reply the LLM cannot classify must never resolve as approve;
* a selective reply must resolve ONLY what it named — an unmentioned action stays pending
  for the buttons or the timeout sweep, it does not ride along on someone else's "yes";
* an index the model invents must not resolve whatever happens to sit at that position.

The LLM is mocked at ``ainvoke_structured`` (the real boundary); everything between the
verdict and ``resolve_approval`` is the production code under test.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.llm.client import StructuredCallOptions
from app.constants.hil import HIL_LLM_TIMEOUT_SECONDS
from app.services.hil.conversational import (
    UNRELATED_FEEDBACK,
    BatchDecisionResult,
    BatchItemDecision,
    DecisionResult,
    interpret_batch_decision_message,
    interpret_decision_message,
    resolve_pending_from_message,
)
from app.services.hil.resolution import ApprovalRequestNotFoundError

from .conftest import CONVERSATION_ID, USER_ID, make_record

MODULE = "app.services.hil.conversational"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def resolver():
    """The two sinks a decision can reach, plus the LLM boundary in front of them."""
    with (
        patch(f"{MODULE}.resolve_approval", new=AsyncMock()) as resolve,
        patch(f"{MODULE}.abandon_conversation_approvals", new=AsyncMock()) as abandon,
        patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm,
    ):
        yield {"resolve": resolve, "abandon": abandon, "llm": llm}


def pending(*summaries: str) -> Any:
    """Patch the store to report these approvals as awaiting a decision."""
    records = [
        make_record(approval_id=f"appr-{i}", summary=summary)
        for i, summary in enumerate(summaries, start=1)
    ]
    return patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=records))


def resolved_ids(resolve: AsyncMock) -> list[str]:
    return [call.kwargs["approval_id"] for call in resolve.await_args_list]


def resolved_kinds(resolve: AsyncMock) -> list[str]:
    return [call.kwargs["kind"] for call in resolve.await_args_list]


def prompt_of(llm: AsyncMock) -> str:
    return llm.await_args.args[1]


class TestNothingPending:
    async def test_a_normal_message_costs_no_llm_call(self, resolver: dict) -> None:
        # The resolver sits on the critical path of EVERY chat message. If it classified
        # before checking whether anything was pending, every user would pay an LLM call
        # per message for a feature most of them have switched off.
        with patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[])):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hey") is None
        resolver["llm"].assert_not_awaited()
        resolver["resolve"].assert_not_awaited()


class TestSingleApproval:
    async def test_yes_approves_the_pending_action(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes go ahead")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1"]
        assert resolved_kinds(resolver["resolve"]) == ["approve"]

    async def test_a_decline_carries_the_users_words_to_the_agent(self, resolver: dict) -> None:
        # Feedback is what turns a refusal into a redirect ("send it to Alice instead").
        # Dropping it makes every decline a dead end.
        resolver["llm"].return_value = DecisionResult(
            action="deny", feedback="wrong recipient, use alice@example.com"
        )
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "no, wrong person"
            )

        assert action == "deny"
        call = resolver["resolve"].await_args
        assert call.kwargs["kind"] == "deny"
        assert call.kwargs["feedback"] == "wrong recipient, use alice@example.com"

    async def test_moving_on_abandons_the_paused_run_rather_than_leaving_it_stuck(
        self, resolver: dict
    ) -> None:
        # An unresolved approval hijacks every later message in the conversation and holds
        # the executor's claim on the thread. Moving on must free both.
        resolver["llm"].return_value = DecisionResult(action="unrelated")
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "what's the weather"
            )

        assert action == "unrelated"
        resolver["abandon"].assert_awaited_once_with(CONVERSATION_ID, USER_ID, UNRELATED_FEEDBACK)
        resolver["resolve"].assert_not_awaited()

    async def test_the_classifier_is_shown_what_it_is_deciding_about(self, resolver: dict) -> None:
        # Classifying "yes" against nothing is classifying blind: without the pending
        # action in the prompt the model cannot tell an answer from a new request.
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Delete 400 emails older than 2019"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        text = prompt_of(resolver["llm"])
        assert "Delete 400 emails older than 2019" in text
        assert "yes" in text


class TestAnApprovalCannotCarryAnEdit:
    """An approval runs the tool with its ORIGINAL arguments — there is no arg-editing.

    So "yes but cc finance" is the dangerous reply: read as approve, the email goes out
    WITHOUT the cc and the user believes they asked for it. That is a wrong action taken
    under an apparent yes, which is worse than either refusing or asking again. It must
    become a decline carrying the change, so the agent re-proposes.
    """

    async def test_an_approval_with_a_requested_change_becomes_a_decline(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve", feedback="cc finance")
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "yes but cc finance"
            )

        assert action == "deny"
        call = resolver["resolve"].await_args
        assert call.kwargs["kind"] == "deny", "the un-edited action must NOT run"
        assert call.kwargs["feedback"] == "cc finance", (
            "the change has to reach the agent, or it re-proposes the same wrong action"
        )

    @pytest.mark.parametrize("feedback", [None, "", "   "])
    async def test_a_clean_yes_is_still_an_approval(
        self, resolver: dict, feedback: str | None
    ) -> None:
        # The guard must key on a SUBSTANTIVE change. If any non-None feedback flipped an
        # approval, a classifier that echoes "" or a stray space would make "yes" undeniably
        # unapprovable and the feature would never run anything.
        resolver["llm"].return_value = DecisionResult(action="approve", feedback=feedback)
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action == "approve"
        assert resolver["resolve"].await_args.kwargs["kind"] == "approve"

    async def test_one_edited_item_in_a_batch_is_declined_while_the_clean_one_runs(
        self, resolver: dict
    ) -> None:
        # The batch path applies the same rule per item, and must not let an edited item
        # ride along on the blanket approval of its neighbour.
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="approve", feedback="make it tomorrow"),
            ],
        )
        with pending("Send email — to: bob@example.com", "Create event — title: standup"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes, but move the 2nd")

        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-2"]
        assert resolved_kinds(resolver["resolve"]) == ["approve", "deny"]
        assert resolver["resolve"].await_args_list[1].kwargs["feedback"] == "make it tomorrow"


class TestBatch:
    """Several approvals pending at once — the concurrent-subagent burst. A blanket answer
    applies to all of them; a selective one must apply to nothing it did not name."""

    async def test_a_blanket_yes_approves_every_pending_action(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="approve"),
                BatchItemDecision(index=3, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack", "Create calendar event"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "yes, all of them"
            )

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-2", "appr-3"]

    async def test_a_blanket_no_declines_every_pending_action(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="deny"),
                BatchItemDecision(index=2, action="deny"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "no, don't")

        assert action == "deny"
        assert resolved_kinds(resolver["resolve"]) == ["deny", "deny"]

    async def test_a_selective_answer_leaves_everything_it_did_not_name_pending(
        self, resolver: dict
    ) -> None:
        # A non-exclusive partial answer ("approve the email one") resolves only what it
        # names; an unmentioned action stays pending for the buttons or the sweep. (An
        # EXCLUSIVE answer like "just the email" instead denies the rest — that is the
        # classifier's job, mocked here; this pins the code path for a 'leave' verdict.)
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="leave"),
                BatchItemDecision(index=3, action="leave"),
            ],
        )
        with pending("Send email", "Post to Slack", "Create calendar event"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "approve the email one"
            )

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1"]

    async def test_a_question_about_the_actions_resolves_nothing(self, resolver: dict) -> None:
        # "who is bob@example.com?" is not a decision. Answering it must not double as one.
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="leave"),
                BatchItemDecision(index=2, action="leave"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "who is bob@example.com?"
            )

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()

    async def test_a_mixed_answer_reports_approve_because_something_was_approved(
        self, resolver: dict
    ) -> None:
        # The return value drives whether the caller streams "going ahead" or "I won't".
        # Any approval means work is now in flight, so it must win over a sibling denial.
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="deny"),
                BatchItemDecision(index=2, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "skip the email, do the slack one"
            )

        assert action == "approve"
        assert resolved_kinds(resolver["resolve"]) == ["deny", "approve"]

    async def test_moving_on_abandons_the_whole_batch(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=True)
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "actually, book me a flight to Tokyo"
            )

        assert action == "unrelated"
        resolver["abandon"].assert_awaited_once()
        resolver["resolve"].assert_not_awaited()

    async def test_the_numbered_list_starts_at_one_to_match_the_index_contract(
        self, resolver: dict
    ) -> None:
        # BatchItemDecision.index is documented 1-based and the code subtracts 1. If the
        # prompt numbered from 0, every verdict would land on the neighbouring action —
        # "approve the email" would post to Slack instead.
        resolver["llm"].return_value = BatchDecisionResult(unrelated=False)
        with pending("Send email", "Post to Slack"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hmm")

        text = prompt_of(resolver["llm"])
        assert "1. Send email" in text
        assert "2. Post to Slack" in text
        assert "0. Send email" not in text


class TestInventedIndexes:
    """The index comes from an LLM, so it is untrusted input. An out-of-range value must
    be dropped, never wrapped, clamped, or used to index from the end of the list."""

    @pytest.mark.parametrize("index", [0, -1, -2, 3, 99])
    async def test_an_out_of_range_index_resolves_nothing(self, resolver: dict, index: int) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False, decisions=[BatchItemDecision(index=index, action="approve")]
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action is None
        resolver["resolve"].assert_not_awaited()

    async def test_a_valid_index_still_applies_alongside_a_bogus_one(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=99, action="approve"),
                BatchItemDecision(index=2, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "the slack one")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-2"]


class TestClassifierFailure:
    """A broken LLM must never resolve as approve — and never as a genuine ``unrelated``
    either. Single and batch both fail toward leaving everything pending: an error is not
    the same signal as the user moving on, so a transient hiccup must not abandon a
    legitimate pending action. The buttons or the timeout sweep still resolve it."""

    async def test_a_single_pending_approval_is_left_pending_rather_than_abandoned(
        self, resolver: dict
    ) -> None:
        # An LLM error leaves the single approval pending: nothing is resolved and the run
        # is NOT abandoned (that would silently decline a legitimate pending action on a
        # transient hiccup). Matches the batch path.
        resolver["llm"].side_effect = ConnectionError("provider down")
        with pending("Send email — to: bob@example.com"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()

    async def test_a_batch_is_left_pending_rather_than_abandoned(self, resolver: dict) -> None:
        # A batch is a burst of parallel work the user is mid-review on. Abandoning it on a
        # provider hiccup would throw away a review they already started, so this fails the
        # other way: everything stays pending for the buttons or the sweep.
        resolver["llm"].side_effect = ConnectionError("provider down")
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()


class TestRacingDecisions:
    """The user can click a button and type "yes" at the same time, and the sweep can fire
    mid-classification. A decision that lost the race must not break the others."""

    async def test_an_already_resolved_item_does_not_block_the_rest_of_the_batch(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="approve"),
            ],
        )
        resolver["resolve"].side_effect = [ApprovalRequestNotFoundError(), None]
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-2"]

    async def test_an_already_resolved_single_approval_does_not_raise(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        resolver["resolve"].side_effect = ApprovalRequestNotFoundError()
        with pending("Send email"):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") == "approve"

    async def test_a_forbidden_approval_is_swallowed_the_same_way(self, resolver: dict) -> None:
        """A decision that lost an ownership race (approval belongs to another
        user) must read as "already handled", not blow up the chat turn."""
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        resolver["llm"].return_value = DecisionResult(action="approve")
        resolver["resolve"].side_effect = ApprovalRequestForbiddenError()
        with pending("Send email"):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") == "approve"


class TestTheClassifierCall:
    """What the two interpreters hand the LLM boundary. The label is what the
    call is metered and traced under — the batch and single paths are separate
    lanes only because their labels differ — and the timeout is what stops a
    hung provider from holding a chat turn open for the client default."""

    async def test_the_single_approval_call_is_labelled_and_bounded(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_ainvoke_structured(
            schema: type[DecisionResult],
            prompt: Any,
            *,
            label: str,
            config: Any = None,
            options: StructuredCallOptions | None = None,
        ) -> DecisionResult:
            captured.update(schema=schema, label=label, options=options)
            return DecisionResult(action="approve")

        with patch(f"{MODULE}.ainvoke_structured", fake_ainvoke_structured):
            result = await interpret_decision_message(
                "yes", ["Send email — to: bob@example.com"], user_id=USER_ID
            )

        assert result == DecisionResult(action="approve")
        assert captured["schema"] is DecisionResult
        assert captured["label"] == "hil_conversational_resolve"
        assert captured["options"] == StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS)

    async def test_the_batch_call_is_labelled_and_bounded(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_ainvoke_structured(
            schema: type[BatchDecisionResult],
            prompt: Any,
            *,
            label: str,
            config: Any = None,
            options: StructuredCallOptions | None = None,
        ) -> BatchDecisionResult:
            captured.update(schema=schema, label=label, options=options)
            return BatchDecisionResult(unrelated=False)

        with patch(f"{MODULE}.ainvoke_structured", fake_ainvoke_structured):
            result = await interpret_batch_decision_message(
                "yes", ["Send email", "Post to Slack"], user_id=USER_ID
            )

        assert result == BatchDecisionResult(unrelated=False)
        assert captured["schema"] is BatchDecisionResult
        assert captured["label"] == "hil_conversational_resolve_batch"
        assert captured["options"] == StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS)
