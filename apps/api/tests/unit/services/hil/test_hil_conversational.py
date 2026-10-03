"""Attacks on the chat-reply resolver (app/services/hil/conversational.py).

This is the ONLY decision surface a text-only channel has: WhatsApp and Telegram have no
approve/deny buttons, so "yes" typed into a chat is the whole approval UI. That makes the
classifier a security boundary, and the attacks that matter are the ones that turn an
ambiguous or broken reply into an action:

* a reply the LLM cannot classify must never resolve as approve;
* a selective reply must resolve ONLY what it named — an unmentioned action stays pending
  for the buttons or the timeout sweep, it does not ride along on someone else's "yes";
* an index the model invents must not resolve whatever happens to sit at that position.

The LLM is mocked at ainvoke_structured (the real boundary); everything between the
verdict and resolve_approval is the production code under test.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.agents.llm.client import StructuredCallOptions, silent_metered_config
from app.constants.hil import (
    HIL_JEV_REPLY_APPROVE_LINE,
    HIL_LLM_TIMEOUT_SECONDS,
    UNRELATED_FEEDBACK,
)
from app.models.hil_models import (
    ApprovalLedgerDocument,
    BatchDecisionResult,
    BatchItemDecision,
    DecisionResult,
    LedgerState,
)
from app.models.message_models import MessageDict
from app.services.hil.bridge import build_action_detail
from app.services.hil.conversational import (
    LEDGER_OUTCOME_TEXT,
    _batch_prompt,
    _prompt,
    classify_batch_with_llm,
    classify_with_llm,
    ledger_outcome_text,
    resolve_pending_from_message,
)
from app.services.hil.ledger_decide import LedgerDecision
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)

from .conftest import CONVERSATION_ID, USER_ID, jev_reply_body, make_record, serve_jev

MODULE = "app.services.hil.conversational"


@pytest.fixture(autouse=True)
def _quiet_log():
    with patch(f"{MODULE}.log"):
        yield


@pytest.fixture
def resolver():
    """Patch the two sinks a decision can reach, plus the LLM boundary in front of them.

    JEV is off here: these tests pin the LLM classifier and everything after it.
    """
    with (
        patch(f"{MODULE}.resolve_approval", new=AsyncMock()) as resolve,
        patch(f"{MODULE}.abandon_conversation_approvals", new=AsyncMock()) as abandon,
        patch(f"{MODULE}.ainvoke_structured", new=AsyncMock()) as llm,
        patch(f"{MODULE}.approval_ledger_repository") as ledger,
        patch(f"{MODULE}.is_jev_reply_enabled", new=AsyncMock(return_value=False)) as jev_flag,
    ):
        ledger.list_open = AsyncMock(return_value=[])
        yield {"resolve": resolve, "abandon": abandon, "llm": llm, "jev_flag": jev_flag}


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
    """Approvals arrive in a concurrent-subagent burst.

    A blanket answer resolves all of them; a selective one resolves only what it names.
    """

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
        # A non-exclusive answer resolves only what it names; unmentioned actions stay pending.
        # An EXCLUSIVE answer ("just the email") instead denies the rest — that's the
        # classifier's job (mocked here); this pins the code path for a 'leave' verdict.
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
    """The index comes from an LLM, so it is untrusted input.

    An out-of-range value must be dropped, never wrapped, clamped, or used to index from the end.
    """

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
    """A broken LLM must never resolve as approve, and never as a genuine unrelated either.

    Single and batch both fail toward leaving everything pending, since a transient hiccup
    is not the same signal as the user moving on. The buttons or the timeout sweep still
    resolve it.
    """

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
    """A button click, a typed "yes", and the timeout sweep can all fire at once.

    A decision that lost the race must not break the others.
    """

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
        """A forbidden decision (wrong owner) is swallowed like an already-resolved one."""
        from app.services.hil.resolution import ApprovalRequestForbiddenError

        resolver["llm"].return_value = DecisionResult(action="approve")
        resolver["resolve"].side_effect = ApprovalRequestForbiddenError()
        with pending("Send email"):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") == "approve"


class TestTheClassifierCall:
    """What the two LLM classifiers hand the LLM boundary.

    The label is what the call is metered and traced under, so batch and single stay
    separate lanes; the timeout stops a hung provider from holding a chat turn open.
    """

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
            result = await classify_with_llm(
                "yes", "Send email — to: bob@example.com", user_id=USER_ID
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
            result = await classify_batch_with_llm(
                "yes", ["Send email", "Post to Slack"], user_id=USER_ID
            )

        assert result == BatchDecisionResult(unrelated=False)
        assert captured["schema"] is BatchDecisionResult
        assert captured["label"] == "hil_conversational_resolve_batch"
        assert captured["options"] == StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS)


class TestTheSingleApprovalPromptStatesItsRules:
    """The classifier is the whole approval UI on a text-only channel, so each rule is asserted as the instruction it gives.

    A rule that goes missing is not a formatting change: it is the model quietly
    approving something the user did not agree to.
    """

    @staticmethod
    def _text() -> str:
        return _prompt("yes", "Send email", None)

    def test_it_says_the_user_typed_instead_of_clicking_approve_or_decline(self) -> None:
        assert (
            "They did NOT click approve or decline. They replied in chat. "
            "Classify what the reply means."
        ) in self._text()

    def test_approve_is_reserved_for_the_action_exactly_as_proposed(self) -> None:
        assert (
            "- 'approve': the user accepts the pending action EXACTLY as proposed, with "
            "no change (e.g. 'yes', 'go ahead', 'ok send it'). Leave `feedback` empty."
        ) in self._text()

    def test_deny_covers_a_refusal_a_correction_and_a_conditional_yes(self) -> None:
        assert (
            "- 'deny': the user does NOT want the action run as proposed. This INCLUDES a "
            "plain refusal ('no', 'don't')"
        ) in self._text()

    def test_unrelated_is_only_a_new_request_that_does_not_object(self) -> None:
        assert (
            "- 'unrelated': a brand-new, standalone request that does NOT object to the "
            "pending action and does not reference it"
        ) in self._text()

    def test_the_conversation_history_can_never_overturn_a_clear_yes_or_no(self) -> None:
        assert (
            "background for interpreting an "
            "ambiguous reply, never grounds to overturn a clear yes or no."
        ) in self._text()

    def test_an_action_the_user_wants_changed_is_never_approved(self) -> None:
        assert (
            "that is 'deny' with the change in "
            "`feedback`. Never approve an action the user wants changed."
        ) in self._text()


class TestTheBatchPromptStatesItsRules:
    """Batch adds per-action arithmetic to the same boundary: whose "yes" covers which action."""

    @staticmethod
    def _text() -> str:
        return _batch_prompt("just the email", ["Send email", "Post to Slack"], None)

    def test_a_selective_answer_decides_each_action_it_names(self) -> None:
        assert (
            "every action. A selective answer names some actions: mark each named one "
            "approve or deny."
        ) in self._text()

    def test_an_exclusive_answer_denies_every_action_it_did_not_name(self) -> None:
        assert (
            "means the user wants ONLY the "
            "named actions: mark every unnamed action 'deny'. A non-exclusive partial "
            "answer"
        ) in self._text()

    def test_a_change_attached_to_an_action_is_a_denial_carrying_that_change(self) -> None:
        assert (
            "(put "
            "the correction in its `feedback`). The assistant cannot edit an action's "
            "arguments"
        ) in self._text()


HISTORY: list[MessageDict] = [{"role": "user", "content": "draft the quarterly deck email"}]


class TestTheClassifierSeesTheReplyAndItsContext:
    """Both barrier paths hand the classifier the user's actual reply and the recent turns."""

    async def test_single_prompt_carries_reply_and_history_and_decides_as_the_user(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email"):
            await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "sure thing", history=HISTORY
            )

        text = prompt_of(resolver["llm"])
        assert "'sure thing'" in text
        assert "draft the quarterly deck email" in text
        assert resolver["resolve"].await_args.kwargs["user_id"] == USER_ID

    async def test_batch_prompt_carries_reply_and_history_and_decides_as_the_user(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="deny"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "first yes second no", history=HISTORY
            )

        text = prompt_of(resolver["llm"])
        assert "'first yes second no'" in text
        assert "draft the quarterly deck email" in text
        assert [c.kwargs["user_id"] for c in resolver["resolve"].await_args_list] == [
            USER_ID,
            USER_ID,
        ]

    async def test_moving_on_from_a_batch_abandons_it_with_the_moved_on_reason(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=True)
        with pending("Send email", "Post to Slack"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "book a flight")

        resolver["abandon"].assert_awaited_once_with(CONVERSATION_ID, USER_ID, UNRELATED_FEEDBACK)


def _ledger_row(
    approval_id: str, state: LedgerState = LedgerState.PENDING
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="send_email",
        summary=f"Send email {approval_id}",
        state=state,
    )


def _committed(approval_id: str, state: LedgerState) -> LedgerDecision:
    return LedgerDecision(
        committed=True, approval_id=approval_id, prior_state=LedgerState.PENDING, state=state
    )


def decided(decide: AsyncMock) -> list[tuple[str, str, str | None]]:
    """Each ledger decision as (approval_id, kind, feedback)."""
    return [(c.args[0], c.kwargs["kind"], c.kwargs["feedback"]) for c in decide.await_args_list]


def assert_abandoned_as_the_user(ledger: dict[str, AsyncMock]) -> None:
    """Moved-on denials read this conversation's rows and carry no row version."""
    assert {c.args for c in ledger["list_open"].await_args_list} == {(CONVERSATION_ID,)}
    assert {(c.kwargs["user_id"], c.kwargs["v"]) for c in ledger["decide"].await_args_list} == {
        (USER_ID, None)
    }


class TestLedgerRows:
    """Ledger-enabled users' approvals live in approval_ledger; a chat reply decides them there."""

    @pytest.fixture
    def ledger(self, resolver: dict) -> Iterator[dict[str, AsyncMock]]:
        with (
            patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.approval_ledger_repository") as repo,
            patch(f"{MODULE}.decide_ledger", new=AsyncMock()) as decide,
        ):
            repo.list_open = AsyncMock(return_value=[])
            decide.side_effect = lambda approval_id, **kw: _committed(
                approval_id, LedgerState.APPROVED if kw["kind"] == "approve" else LedgerState.DENIED
            )
            yield {"list_open": repo.list_open, "decide": decide, **resolver}

    async def test_a_single_pending_row_is_decided_by_the_reply(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [
            _ledger_row("ap_1"),
            _ledger_row("ap_q", LedgerState.APPROVED),
        ]
        ledger["llm"].return_value = DecisionResult(action="approve")

        action = await resolve_pending_from_message(
            CONVERSATION_ID, USER_ID, "yes send it", history=HISTORY
        )

        assert action == "approve"
        ledger["list_open"].assert_awaited_once_with(CONVERSATION_ID)
        ledger["decide"].assert_awaited_once_with(
            "ap_1", user_id=USER_ID, kind="approve", feedback=None, v=None
        )
        text = prompt_of(ledger["llm"])
        assert "Send email ap_1" in text
        assert "'yes send it'" in text
        assert "draft the quarterly deck email" in text
        ledger["resolve"].assert_not_awaited()

    async def test_an_approval_with_a_change_denies_the_row_with_that_change(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1")]
        ledger["llm"].return_value = DecisionResult(action="approve", feedback="cc finance")

        action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes but cc finance")

        assert action == "deny"
        assert decided(ledger["decide"]) == [("ap_1", "deny", "cc finance")]

    async def test_moving_on_denies_every_pending_row_and_skips_queued_ones(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [
            _ledger_row("ap_1"),
            _ledger_row("ap_q", LedgerState.APPROVED),
        ]
        ledger["llm"].return_value = DecisionResult(action="unrelated")

        action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "what's the weather")

        assert action == "unrelated"
        assert decided(ledger["decide"]) == [("ap_1", "deny", UNRELATED_FEEDBACK)]
        assert_abandoned_as_the_user(ledger)
        ledger["abandon"].assert_not_awaited()

    async def test_a_batch_of_rows_is_decided_per_item(self, ledger: dict[str, AsyncMock]) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1"), _ledger_row("ap_2")]
        ledger["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="deny", feedback="not that channel"),
            ],
        )

        action = await resolve_pending_from_message(
            CONVERSATION_ID, USER_ID, "first yes, second no", history=HISTORY
        )

        assert action == "approve"
        assert decided(ledger["decide"]) == [
            ("ap_1", "approve", None),
            ("ap_2", "deny", "not that channel"),
        ]
        assert all(c.kwargs["user_id"] == USER_ID for c in ledger["decide"].await_args_list)
        text = prompt_of(ledger["llm"])
        assert "1. Send email ap_1" in text and "2. Send email ap_2" in text
        assert "'first yes, second no'" in text
        assert "draft the quarterly deck email" in text

    async def test_moving_on_from_a_batch_of_rows_denies_them_all(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1"), _ledger_row("ap_2")]
        ledger["llm"].return_value = BatchDecisionResult(unrelated=True)

        action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "book a flight")

        assert action == "unrelated"
        assert decided(ledger["decide"]) == [
            ("ap_1", "deny", UNRELATED_FEEDBACK),
            ("ap_2", "deny", UNRELATED_FEEDBACK),
        ]
        assert_abandoned_as_the_user(ledger)
        ledger["abandon"].assert_not_awaited()

    async def test_nothing_pending_in_the_ledger_costs_no_llm_call(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_q", LedgerState.APPROVED)]

        assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hey") is None
        ledger["llm"].assert_not_awaited()

    @pytest.mark.parametrize(
        "error",
        [ApprovalRequestNotFoundError(), ApprovalRequestForbiddenError()],
        ids=["gone", "foreign"],
    )
    async def test_an_undecidable_row_does_not_stop_the_rest_being_abandoned(
        self, ledger: dict[str, AsyncMock], error: Exception
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1"), _ledger_row("ap_2")]
        ledger["llm"].return_value = BatchDecisionResult(unrelated=True)
        ledger["decide"].side_effect = [
            error,
            _committed("ap_2", LedgerState.DENIED),
        ]

        assert (
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "new topic") == "unrelated"
        )
        assert [c.args[0] for c in ledger["decide"].await_args_list] == ["ap_1", "ap_2"]

    @pytest.mark.parametrize(
        "error",
        [ApprovalRequestNotFoundError(), ApprovalRequestForbiddenError()],
        ids=["gone", "foreign"],
    )
    async def test_an_undecidable_row_is_tolerated(
        self, ledger: dict[str, AsyncMock], error: Exception
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1")]
        ledger["llm"].return_value = DecisionResult(action="approve")
        ledger["decide"].side_effect = error

        assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") == "approve"

    async def test_a_lost_race_is_reported_with_the_rows_real_outcome(
        self, ledger: dict[str, AsyncMock]
    ) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1")]
        ledger["llm"].return_value = DecisionResult(action="approve")
        ledger["decide"].side_effect = None
        ledger["decide"].return_value = LedgerDecision(
            committed=False,
            approval_id="ap_1",
            prior_state=LedgerState.DENIED,
            state=LedgerState.DENIED,
        )

        with patch(f"{MODULE}.log") as log:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        log.warning.assert_called_once()
        assert "lost the race" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {
            "approval_id": "ap_1",
            "state": "denied",
            "outcome": LEDGER_OUTCOME_TEXT[LedgerState.DENIED],
        }

    async def test_a_committed_decision_reports_nothing(self, ledger: dict[str, AsyncMock]) -> None:
        ledger["list_open"].return_value = [_ledger_row("ap_1")]
        ledger["llm"].return_value = DecisionResult(action="approve")

        with patch(f"{MODULE}.log") as log:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        log.warning.assert_not_called()


class TestLedgerOutcomeText:
    def test_a_settled_state_reads_as_its_ground_truth(self) -> None:
        assert (
            ledger_outcome_text(LedgerState.EXECUTED) == LEDGER_OUTCOME_TEXT[LedgerState.EXECUTED]
        )

    def test_a_state_with_no_narration_falls_back_to_its_name(self) -> None:
        assert ledger_outcome_text(LedgerState.EXECUTING) == "executing"


class TestNoHistory:
    async def test_a_reply_with_no_history_sends_no_conversation_section(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        text = prompt_of(resolver["llm"])
        assert "RECENT CONVERSATION" not in text
        record = make_record(summary="Send email")
        detail = build_action_detail(record.summary, record.args)
        assert f"{detail}\n\nTHE USER'S REPLY" in text


def assert_logged_jev_fallback(log: MagicMock, error_type: type[Exception], error: str) -> None:
    """Assert one warning names the JEV failure and its cause, so a fallback is never silent."""
    log.warning.assert_called_once()
    assert (
        "JEV reply classifier failed; falling back to the LLM classifier"
        in (log.warning.call_args.args[0])
    )
    assert log.warning.call_args.kwargs["error_type"] == error_type.__name__
    assert log.warning.call_args.kwargs["error"] == error


class TestJevClassifiesTheReply:
    """With the flag on, JEV reads the reply; the LLM only runs when JEV cannot answer.

    JEV is mocked at the HTTP boundary, so the question building, the approve
    line, the unanimity rule and the mapping onto decisions all run for real.
    """

    @pytest.fixture(autouse=True)
    def _jev_on(self, resolver: dict) -> None:
        resolver["jev_flag"].return_value = True

    async def test_a_confident_yes_approves_without_an_llm_call(self, resolver: dict) -> None:
        with (
            pending("Send email — to: bob@example.com"),
            serve_jev(jev_reply_body(("approve", 0.99))),
        ):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes send it")

        assert action == "approve"
        assert resolved_kinds(resolver["resolve"]) == ["approve"]
        assert resolver["resolve"].await_args.kwargs["feedback"] is None
        resolver["llm"].assert_not_awaited()

    async def test_a_decline_carries_the_reply_verbatim_to_the_agent(self, resolver: dict) -> None:
        # JEV returns no text, so the user's own words are the correction: dropping them
        # would turn "send it to Alice instead" into a dead-end refusal.
        with pending("Send email — to: bob@example.com"), serve_jev(jev_reply_body(("deny", 0.97))):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "no, send it to alice@example.com instead"
            )

        assert action == "deny"
        call = resolver["resolve"].await_args
        assert call.kwargs["kind"] == "deny"
        assert call.kwargs["feedback"] == "no, send it to alice@example.com instead"

    async def test_an_approve_under_the_line_runs_nothing(self, resolver: dict) -> None:
        # A coin-flip approve is the one verdict that executes an action; under the line
        # it must leave the approval for the user to answer again, not run it.
        below = round(HIL_JEV_REPLY_APPROVE_LINE - 0.01, 2)
        with pending("Send email"), serve_jev(jev_reply_body(("approve", below))):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "sure i guess")

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()

    async def test_the_decisions_call_carries_the_reply_and_recent_turns(
        self, resolver: dict
    ) -> None:
        with pending("Send email"), serve_jev(jev_reply_body(("approve", 0.99))) as client:
            await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "sure thing", history=HISTORY
            )

        state = client.post.await_args.kwargs["json"]["state"]
        assert state["reply"] == "sure thing"
        record = make_record(summary="Send email")
        assert state["pending_actions"] == [
            {"number": 1, "action": build_action_detail(record.summary, record.args)}
        ]
        assert state["recent_conversation"] == HISTORY
        assert resolver["jev_flag"].await_args.args == (USER_ID,)

    async def test_a_batch_decisions_call_carries_every_action_the_reply_and_turns(
        self, resolver: dict
    ) -> None:
        body = jev_reply_body(("approve", 0.99), ("approve", 0.99))
        with pending("Send email", "Post to Slack"), serve_jev(body) as client:
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "both", history=HISTORY)

        state = client.post.await_args.kwargs["json"]["state"]
        assert state["reply"] == "both"
        assert [a["action"].split("\n")[0] for a in state["pending_actions"]] == [
            "Send email",
            "Post to Slack",
        ]
        assert state["recent_conversation"] == HISTORY
        assert resolver["jev_flag"].await_args.args == (USER_ID,)

    async def test_an_approve_on_the_line_runs(self, resolver: dict) -> None:
        with (
            pending("Send email"),
            serve_jev(jev_reply_body(("approve", HIL_JEV_REPLY_APPROVE_LINE))),
        ):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "ok") == "approve"

    async def test_a_question_leaves_the_approval_pending(self, resolver: dict) -> None:
        with pending("Send email"), serve_jev(jev_reply_body(("leave", 0.98))):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "who is bob?")

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()

    async def test_moving_on_abandons_the_paused_run(self, resolver: dict) -> None:
        with pending("Send email"), serve_jev(jev_reply_body(("unrelated", 0.99))):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "tell me a joke")

        assert action == "unrelated"
        resolver["abandon"].assert_awaited_once_with(CONVERSATION_ID, USER_ID, UNRELATED_FEEDBACK)
        resolver["resolve"].assert_not_awaited()

    async def test_an_exclusive_answer_approves_one_and_declines_the_rest(
        self, resolver: dict
    ) -> None:
        body = jev_reply_body(("approve", 0.95), ("deny", 0.99))
        with pending("Send email", "Post to Slack"), serve_jev(body):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "just the email")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-2"]
        assert resolved_kinds(resolver["resolve"]) == ["approve", "deny"]
        assert resolver["resolve"].await_args_list[1].kwargs["feedback"] == "just the email"

    async def test_an_unnamed_action_approved_on_a_coin_flip_stays_pending(
        self, resolver: dict
    ) -> None:
        # Seen live: "approve the email" drew approve@0.30 on the Slack post it never
        # named. Only the confidently approved action may run.
        body = jev_reply_body(("approve", 0.99), ("approve", 0.30))
        with pending("Send email", "Post to Slack"), serve_jev(body):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "approve the email"
            )

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1"]

    async def test_one_action_reading_unrelated_does_not_abandon_the_batch(
        self, resolver: dict
    ) -> None:
        body = jev_reply_body(("unrelated", 0.6), ("approve", 0.95))
        with pending("Send email", "Post to Slack"), serve_jev(body):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "the slack one")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-2"]
        resolver["abandon"].assert_not_awaited()

    async def test_a_batch_every_action_reads_as_unrelated_is_abandoned(
        self, resolver: dict
    ) -> None:
        body = jev_reply_body(("unrelated", 0.99), ("unrelated", 0.97))
        with pending("Send email", "Post to Slack"), serve_jev(body):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "book a flight")

        assert action == "unrelated"
        resolver["abandon"].assert_awaited_once_with(CONVERSATION_ID, USER_ID, UNRELATED_FEEDBACK)

    @pytest.mark.parametrize(
        ("failure", "error_type", "error"),
        [
            (httpx.ConnectError("decisions API down"), httpx.ConnectError, "decisions API down"),
            (jev_reply_body(("maybe", 0.9)), ValueError, "unknown JEV reply choice: 'maybe'"),
            (
                {"answers": {}},
                ValueError,
                "JEV reply answer missing for question 'action_1'",
            ),
        ],
        ids=["transport", "unknown-choice", "missing-answer"],
    )
    async def test_a_jev_failure_falls_back_to_the_llm(
        self,
        resolver: dict,
        failure: dict | Exception,
        error_type: type[Exception],
        error: str,
    ) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email"), serve_jev(failure), patch(f"{MODULE}.log") as log:
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action == "approve"
        assert resolved_kinds(resolver["resolve"]) == ["approve"]
        assert resolver["llm"].await_args.kwargs["config"] == silent_metered_config(USER_ID)
        assert_logged_jev_fallback(log, error_type, error)

    async def test_a_batch_jev_failure_falls_back_to_the_llm(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False, decisions=[BatchItemDecision(index=2, action="deny")]
        )
        with (
            pending("Send email", "Post to Slack"),
            serve_jev(httpx.ReadTimeout("slow")),
            patch(f"{MODULE}.log") as log,
        ):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "not slack")

        assert action == "deny"
        assert resolved_ids(resolver["resolve"]) == ["appr-2"]
        assert resolver["llm"].await_args.kwargs["config"] == silent_metered_config(USER_ID)
        assert_logged_jev_fallback(log, httpx.ReadTimeout, "slow")

    async def test_the_flag_off_never_calls_jev(self, resolver: dict) -> None:
        resolver["jev_flag"].return_value = False
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email"), serve_jev(jev_reply_body(("deny", 1.0))) as client:
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action == "approve"
        client.post.assert_not_awaited()
        assert resolver["jev_flag"].await_args.args == (USER_ID,)

    async def test_ledger_rows_are_decided_from_the_jev_verdict(self, resolver: dict) -> None:
        with (
            patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.approval_ledger_repository") as repo,
            patch(f"{MODULE}.decide_ledger", new=AsyncMock()) as decide,
            serve_jev(jev_reply_body(("deny", 0.9))),
        ):
            repo.list_open = AsyncMock(return_value=[_ledger_row("ap_1")])
            decide.return_value = _committed("ap_1", LedgerState.DENIED)
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "not now")

        assert action == "deny"
        assert decided(decide) == [("ap_1", "deny", "not now")]
