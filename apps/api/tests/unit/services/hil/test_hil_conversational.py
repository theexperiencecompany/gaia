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

from app.agents.llm.client import silent_metered_config
from app.constants.hil import (
    HIL_CLASSIFIER_MAX_ARG_CHARS,
    HIL_CLASSIFIER_MAX_DETAIL_CHARS,
    HIL_LLM_TIMEOUT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.services.hil import conversational as hil_conversational
from app.services.hil.conversational import (
    UNRELATED_FEEDBACK,
    BatchDecisionResult,
    BatchItemDecision,
    DecisionResult,
    _batch_prompt,
    _history_block,
    _prompt,
    _safe_resolve,
    interpret_batch_decision_message,
    interpret_decision_message,
    resolve_pending_from_message,
)
from app.services.hil.resolution import ApprovalRequestForbidden, ApprovalRequestNotFound
from app.utils.general_utils import clip_text

from .conftest import CONVERSATION_ID, USER_ID, make_record

MODULE = "app.services.hil.conversational"

HISTORY: list[dict[str, str]] = [
    {"role": "user", "content": "hey"},
    {"role": "assistant", "content": "sure"},
]

SINGLE_ACTION = "Send email — to: bob@example.com"
BATCH_ACTIONS = ["Send email", "Post to Slack"]

# The classifier prompt is pinned VERBATIM: mutmut's string mutations (XX-wrapping,
# case flips) and call-arg mutations all change the exact bytes a model sees, so only
# an exact-equality assertion can tell a real prompt from a subtly broken one.
EXPECTED_PROMPT_SINGLE_NO_HISTORY = (
    "The user has a pending action awaiting their approval. They did NOT click "
    "approve or decline — they replied in chat. Classify what the reply means.\n\n"
    "PENDING ACTION (what the assistant is waiting to do):\n"
    "Send email — to: bob@example.com\n\n"
    "THE USER'S REPLY:\n"
    "'yes'\n\n"
    "Classify the reply as exactly one of:\n"
    "- 'approve' — the user accepts the pending action EXACTLY as proposed, with "
    "no change (e.g. 'yes', 'go ahead', 'ok send it'). Leave `feedback` empty.\n"
    "- 'deny' — the user does NOT want the action run as proposed. This INCLUDES a "
    "plain refusal ('no', 'don't'), a redirect or correction ('no, send it to Bob "
    "instead', 'actually make it tomorrow'), AND an acceptance that attaches ANY "
    "change, addition, or condition to it ('yes but cc finance', 'ok, but shorten "
    "it first'). The assistant cannot edit the action's arguments, so any requested "
    "change means the current action is wrong: mark it 'deny' and put the change "
    "verbatim in `feedback`.\n"
    "- 'unrelated' — a brand-new, standalone request that does NOT object to the "
    "pending action and does not reference it (e.g. the pending action is 'send "
    "email' and the user asks 'what's on my calendar tomorrow?').\n\n"
    "Rules:\n"
    "- An unambiguous 'yes'/'no' is decisive on its own. Honor it directly. The "
    "recent conversation and action details are background for interpreting an "
    "ambiguous reply — never grounds to overturn a clear yes or no.\n"
    "- Only 'approve' when the action should run UNCHANGED. If the reply adds, "
    "changes, or conditions anything about it, that is 'deny' with the change in "
    "`feedback` — never approve an action the user wants changed.\n"
    "- If the reply objects to, corrects, or countermands the pending action, it "
    "is 'deny' (with the correction in `feedback`) even when it also proposes a "
    "different action. 'unrelated' is only for a reply that adds a new topic "
    "WITHOUT objecting to the pending action.\n"
    "- If unsure whether the reply bears on the pending action and it expresses "
    "any objection, choose 'deny'."
)

EXPECTED_PROMPT_SINGLE_WITH_HISTORY = (
    "The user has a pending action awaiting their approval. They did NOT click "
    "approve or decline — they replied in chat. Classify what the reply means.\n\n"
    "PENDING ACTION (what the assistant is waiting to do):\n"
    "Send email — to: bob@example.com\n\n"
    "RECENT CONVERSATION (oldest to newest, context only):\n"
    "user: hey\n"
    "assistant: sure\n\n"
    "THE USER'S REPLY:\n"
    "'no'\n\n"
    "Classify the reply as exactly one of:\n"
    "- 'approve' — the user accepts the pending action EXACTLY as proposed, with "
    "no change (e.g. 'yes', 'go ahead', 'ok send it'). Leave `feedback` empty.\n"
    "- 'deny' — the user does NOT want the action run as proposed. This INCLUDES a "
    "plain refusal ('no', 'don't'), a redirect or correction ('no, send it to Bob "
    "instead', 'actually make it tomorrow'), AND an acceptance that attaches ANY "
    "change, addition, or condition to it ('yes but cc finance', 'ok, but shorten "
    "it first'). The assistant cannot edit the action's arguments, so any requested "
    "change means the current action is wrong: mark it 'deny' and put the change "
    "verbatim in `feedback`.\n"
    "- 'unrelated' — a brand-new, standalone request that does NOT object to the "
    "pending action and does not reference it (e.g. the pending action is 'send "
    "email' and the user asks 'what's on my calendar tomorrow?').\n\n"
    "Rules:\n"
    "- An unambiguous 'yes'/'no' is decisive on its own. Honor it directly. The "
    "recent conversation and action details are background for interpreting an "
    "ambiguous reply — never grounds to overturn a clear yes or no.\n"
    "- Only 'approve' when the action should run UNCHANGED. If the reply adds, "
    "changes, or conditions anything about it, that is 'deny' with the change in "
    "`feedback` — never approve an action the user wants changed.\n"
    "- If the reply objects to, corrects, or countermands the pending action, it "
    "is 'deny' (with the correction in `feedback`) even when it also proposes a "
    "different action. 'unrelated' is only for a reply that adds a new topic "
    "WITHOUT objecting to the pending action.\n"
    "- If unsure whether the reply bears on the pending action and it expresses "
    "any objection, choose 'deny'."
)

EXPECTED_PROMPT_BATCH_NO_HISTORY = (
    "The assistant is waiting for the user to approve or decline these "
    "numbered pending actions:\n"
    "1. Send email\n"
    "\n"
    "2. Post to Slack\n"
    "\n"
    "THE USER'S REPLY:\n"
    "'yes'\n\n"
    "Decide per action. A blanket answer applies to all of them: a plain "
    "'yes'/'go ahead' approves every action, a plain 'no'/'don't' declines "
    "every action. A selective answer names some actions — mark each named one "
    "approve or deny. Decide the UNNAMED actions by whether the reply is "
    "exclusive: an exclusive answer ('just the email', 'only the email', 'just "
    "do that and nothing else', 'skip the rest') means the user wants ONLY the "
    "named actions — mark every unnamed action 'deny'. A non-exclusive partial "
    "answer ('approve the email', 'yes to the first one') decides only what it "
    "names and leaves each unnamed action 'leave' (the user may still answer the "
    "rest separately). Also mark an action 'deny' when the reply rejects, "
    "corrects, redirects, or attaches any change/condition to THAT action (put "
    "the correction in its `feedback`) — the assistant cannot edit an action's "
    "arguments, so 'do it but change X' is 'deny' with X in `feedback`, never "
    "'approve'. "
    "If the message asks a question about the actions or is otherwise not a "
    "decision on any of them, mark all 'leave'. Set unrelated=true ONLY when the "
    "message is clearly a new, different request that ignores the pending actions "
    "without objecting to them. An unambiguous 'yes'/'no' is decisive on its own; "
    "the recent conversation is background for ambiguous replies, never grounds to "
    "overturn a clear answer. Extract any feedback or conditions per action."
)

EXPECTED_PROMPT_BATCH_WITH_HISTORY = (
    "The assistant is waiting for the user to approve or decline these "
    "numbered pending actions:\n"
    "1. Send email\n"
    "\n"
    "2. Post to Slack\n"
    "\n"
    "RECENT CONVERSATION (oldest to newest, context only):\n"
    "user: hey\n"
    "assistant: sure\n\n"
    "THE USER'S REPLY:\n"
    "'no'\n\n"
    "Decide per action. A blanket answer applies to all of them: a plain "
    "'yes'/'go ahead' approves every action, a plain 'no'/'don't' declines "
    "every action. A selective answer names some actions — mark each named one "
    "approve or deny. Decide the UNNAMED actions by whether the reply is "
    "exclusive: an exclusive answer ('just the email', 'only the email', 'just "
    "do that and nothing else', 'skip the rest') means the user wants ONLY the "
    "named actions — mark every unnamed action 'deny'. A non-exclusive partial "
    "answer ('approve the email', 'yes to the first one') decides only what it "
    "names and leaves each unnamed action 'leave' (the user may still answer the "
    "rest separately). Also mark an action 'deny' when the reply rejects, "
    "corrects, redirects, or attaches any change/condition to THAT action (put "
    "the correction in its `feedback`) — the assistant cannot edit an action's "
    "arguments, so 'do it but change X' is 'deny' with X in `feedback`, never "
    "'approve'. "
    "If the message asks a question about the actions or is otherwise not a "
    "decision on any of them, mark all 'leave'. Set unrelated=true ONLY when the "
    "message is clearly a new, different request that ignores the pending actions "
    "without objecting to them. An unambiguous 'yes'/'no' is decisive on its own; "
    "the recent conversation is background for ambiguous replies, never grounds to "
    "overturn a clear answer. Extract any feedback or conditions per action."
)

# The public-path variants carry the FULL action detail (summary + bounded args),
# which the interpret-level prompts above do not.
EXPECTED_PROMPT_SINGLE_PUBLIC_WITH_HISTORY = (
    "The user has a pending action awaiting their approval. They did NOT click "
    "approve or decline — they replied in chat. Classify what the reply means.\n\n"
    "PENDING ACTION (what the assistant is waiting to do):\n"
    "Send email — to: bob@example.com\n"
    "Arguments:\n"
    "  to: bob@example.com\n\n"
    "RECENT CONVERSATION (oldest to newest, context only):\n"
    "user: hey\n"
    "assistant: sure\n\n"
    "THE USER'S REPLY:\n"
    "'no'\n\n"
    "Classify the reply as exactly one of:\n"
    "- 'approve' — the user accepts the pending action EXACTLY as proposed, with "
    "no change (e.g. 'yes', 'go ahead', 'ok send it'). Leave `feedback` empty.\n"
    "- 'deny' — the user does NOT want the action run as proposed. This INCLUDES a "
    "plain refusal ('no', 'don't'), a redirect or correction ('no, send it to Bob "
    "instead', 'actually make it tomorrow'), AND an acceptance that attaches ANY "
    "change, addition, or condition to it ('yes but cc finance', 'ok, but shorten "
    "it first'). The assistant cannot edit the action's arguments, so any requested "
    "change means the current action is wrong: mark it 'deny' and put the change "
    "verbatim in `feedback`.\n"
    "- 'unrelated' — a brand-new, standalone request that does NOT object to the "
    "pending action and does not reference it (e.g. the pending action is 'send "
    "email' and the user asks 'what's on my calendar tomorrow?').\n\n"
    "Rules:\n"
    "- An unambiguous 'yes'/'no' is decisive on its own. Honor it directly. The "
    "recent conversation and action details are background for interpreting an "
    "ambiguous reply — never grounds to overturn a clear yes or no.\n"
    "- Only 'approve' when the action should run UNCHANGED. If the reply adds, "
    "changes, or conditions anything about it, that is 'deny' with the change in "
    "`feedback` — never approve an action the user wants changed.\n"
    "- If the reply objects to, corrects, or countermands the pending action, it "
    "is 'deny' (with the correction in `feedback`) even when it also proposes a "
    "different action. 'unrelated' is only for a reply that adds a new topic "
    "WITHOUT objecting to the pending action.\n"
    "- If unsure whether the reply bears on the pending action and it expresses "
    "any objection, choose 'deny'."
)

EXPECTED_PROMPT_BATCH_PUBLIC_WITH_HISTORY = (
    "The assistant is waiting for the user to approve or decline these "
    "numbered pending actions:\n"
    "1. Send email\n"
    "Arguments:\n"
    "  to: bob@example.com\n"
    "\n"
    "2. Post to Slack\n"
    "Arguments:\n"
    "  channel: #general\n"
    "\n"
    "RECENT CONVERSATION (oldest to newest, context only):\n"
    "user: hey\n"
    "assistant: sure\n\n"
    "THE USER'S REPLY:\n"
    "'no'\n\n"
    "Decide per action. A blanket answer applies to all of them: a plain "
    "'yes'/'go ahead' approves every action, a plain 'no'/'don't' declines "
    "every action. A selective answer names some actions — mark each named one "
    "approve or deny. Decide the UNNAMED actions by whether the reply is "
    "exclusive: an exclusive answer ('just the email', 'only the email', 'just "
    "do that and nothing else', 'skip the rest') means the user wants ONLY the "
    "named actions — mark every unnamed action 'deny'. A non-exclusive partial "
    "answer ('approve the email', 'yes to the first one') decides only what it "
    "names and leaves each unnamed action 'leave' (the user may still answer the "
    "rest separately). Also mark an action 'deny' when the reply rejects, "
    "corrects, redirects, or attaches any change/condition to THAT action (put "
    "the correction in its `feedback`) — the assistant cannot edit an action's "
    "arguments, so 'do it but change X' is 'deny' with X in `feedback`, never "
    "'approve'. "
    "If the message asks a question about the actions or is otherwise not a "
    "decision on any of them, mark all 'leave'. Set unrelated=true ONLY when the "
    "message is clearly a new, different request that ignores the pending actions "
    "without objecting to them. An unambiguous 'yes'/'no' is decisive on its own; "
    "the recent conversation is background for ambiguous replies, never grounds to "
    "overturn a clear answer. Extract any feedback or conditions per action."
)


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


def pending(*summaries: str, args: list[dict[str, Any]] | None = None) -> Any:
    """Patch the store to report these approvals as awaiting a decision.

    ``args`` optionally overrides the per-record tool arguments, index-aligned
    (defaults to the shared ``{"to": "bob@example.com"}`` record fixture).
    """
    arg_default = {"to": "bob@example.com"}
    records = [
        make_record(
            approval_id=f"appr-{i}",
            summary=summary,
            args=args[i - 1] if args and i <= len(args) else arg_default,
        )
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
        with patch(f"{MODULE}.list_pending_for_conversation", new=AsyncMock(return_value=[])) as lp:
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "hey") is None
        lp.assert_awaited_once_with(CONVERSATION_ID)
        resolver["llm"].assert_not_awaited()
        resolver["resolve"].assert_not_awaited()


class TestSingleApproval:
    async def test_yes_approves_the_pending_action(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email — to: bob@example.com") as lp:
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes go ahead")

        assert action == "approve"
        lp.assert_awaited_once_with(CONVERSATION_ID)
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

    async def test_the_prompt_is_pinned_verbatim_with_history_and_full_args(
        self, resolver: dict
    ) -> None:
        # Every byte of what the model sees is pinned: a mutation that drops the
        # history window, drops the action's args, mangles the reply, or mis-scopes
        # the metering config must change the exact prompt and fail here.
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email — to: bob@example.com") as lp:
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "no", HISTORY)

        assert action == "approve"
        lp.assert_awaited_once_with(CONVERSATION_ID)
        call = resolver["llm"].await_args
        assert call.args[1] == EXPECTED_PROMPT_SINGLE_PUBLIC_WITH_HISTORY
        assert call.kwargs == {
            "label": "hil_conversational_resolve",
            "timeout": HIL_LLM_TIMEOUT_SECONDS,
            "config": silent_metered_config(USER_ID),
        }

    async def test_resolution_carries_user_id_and_scope(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        with pending("Send email"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert resolver["resolve"].await_args.kwargs == {
            "approval_id": "appr-1",
            "user_id": USER_ID,
            "kind": "approve",
            "feedback": None,
            "scope": "once",
        }


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

    async def test_a_second_approval_after_a_decline_still_reports_approve(
        self, resolver: dict
    ) -> None:
        # The approve/deny tally is read only as "anything approved?" — a lone
        # denial does not cancel the work already set in motion by an earlier
        # approval, and a later approval must not be outvoted by an earlier "no".
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="deny"),
                BatchItemDecision(index=3, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack", "Create calendar event"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "email and the event, not the slack one"
            )

        assert action == "approve"
        assert resolved_kinds(resolver["resolve"]) == ["approve", "deny", "approve"]

    async def test_an_empty_decision_list_resolves_nothing(self, resolver: dict) -> None:
        # The classifier's fail-safe verdict on an LLM hiccup is exactly this
        # shape: unrelated=False with zero decisions. That must mean "nothing
        # was decided", not "everything was declined" — the approvals stay
        # pending for the buttons or the timeout sweep.
        resolver["llm"].return_value = BatchDecisionResult(unrelated=False, decisions=[])
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action is None
        resolver["resolve"].assert_not_awaited()
        resolver["abandon"].assert_not_awaited()

    async def test_moving_on_abandons_the_whole_batch(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=True)
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "actually, book me a flight to Tokyo"
            )

        assert action == "unrelated"
        resolver["abandon"].assert_awaited_once_with(CONVERSATION_ID, USER_ID, UNRELATED_FEEDBACK)
        resolver["resolve"].assert_not_awaited()

    async def test_the_batch_prompt_is_pinned_verbatim_with_history_and_full_args(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=False)
        with pending("Send email", "Post to Slack", args=[{"to": "bob@example.com"}, {"channel": "#general"}]) as lp:
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "no", HISTORY)

        assert action is None
        lp.assert_awaited_once_with(CONVERSATION_ID)
        call = resolver["llm"].await_args
        assert call.args[1] == EXPECTED_PROMPT_BATCH_PUBLIC_WITH_HISTORY
        assert call.kwargs == {
            "label": "hil_conversational_resolve_batch",
            "timeout": HIL_LLM_TIMEOUT_SECONDS,
            "config": silent_metered_config(USER_ID),
        }

    async def test_batch_resolutions_carry_user_id_and_scope(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=2, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes, all of them")

        assert [
            (
                c.kwargs["approval_id"],
                c.kwargs["user_id"],
                c.kwargs["kind"],
                c.kwargs["feedback"],
                c.kwargs["scope"],
            )
            for c in resolver["resolve"].await_args_list
        ] == [
            ("appr-1", USER_ID, "approve", None, "once"),
            ("appr-2", USER_ID, "approve", None, "once"),
        ]

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

    async def test_every_index_out_of_range_resolves_nothing(self, resolver: dict) -> None:
        # The per-item guard is checked for EVERY decision, not just the first:
        # a verdict list that is entirely bogus must leave the whole batch pending.
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=0, action="approve"),
                BatchItemDecision(index=99, action="deny"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action is None
        resolver["resolve"].assert_not_awaited()

    async def test_a_repeated_index_resolves_the_same_approval_twice(self, resolver: dict) -> None:
        # There is no dedup: a model that names the same action twice resolves
        # it twice, and the resolution layer tolerates the second hit as
        # already-resolved. Pinned so a future dedup cannot silently change the
        # call contract the store relies on.
        resolver["llm"].return_value = BatchDecisionResult(
            unrelated=False,
            decisions=[
                BatchItemDecision(index=1, action="approve"),
                BatchItemDecision(index=1, action="approve"),
            ],
        )
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(
                CONVERSATION_ID, USER_ID, "the email, and yes the email again"
            )

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-1"]


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
        resolver["resolve"].side_effect = [ApprovalRequestNotFound(), None]
        with pending("Send email", "Post to Slack"):
            action = await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes")

        assert action == "approve"
        assert resolved_ids(resolver["resolve"]) == ["appr-1", "appr-2"]

    async def test_an_already_resolved_single_approval_does_not_raise(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        resolver["resolve"].side_effect = ApprovalRequestNotFound()
        with pending("Send email"):
            assert await resolve_pending_from_message(CONVERSATION_ID, USER_ID, "yes") == "approve"


class TestPromptContract:
    """The classifier prompt is pinned byte-for-byte. Every one of mutmut's string
    mutations (XX-wrapping, case flips, separators) and its history/context
    argument mutations changes the exact bytes the model sees — the model's verdict
    on a subtly corrupted prompt is not something a unit test can second-guess, so
    the prompt itself is asserted verbatim."""

    def test_single_prompt_without_history_is_exact(self) -> None:
        assert _prompt("yes", [SINGLE_ACTION], None) == EXPECTED_PROMPT_SINGLE_NO_HISTORY

    def test_single_prompt_joins_multiple_actions_with_a_blank_line(self) -> None:
        # The single-action tests pin the whole prompt, but a one-element list never
        # exercises the JOIN — so the separator between multiple actions gets its own
        # exact assertion (a "\n\n" → "XX\n\nXX" mutation changes nothing for one item).
        expected = EXPECTED_PROMPT_SINGLE_NO_HISTORY.replace(
            "Send email — to: bob@example.com", "Send email\n\nPost to Slack", 1
        )
        assert _prompt("yes", BATCH_ACTIONS, None) == expected

    def test_single_prompt_with_history_is_exact(self) -> None:
        assert _prompt("no", [SINGLE_ACTION], HISTORY) == EXPECTED_PROMPT_SINGLE_WITH_HISTORY

    def test_batch_prompt_without_history_is_exact(self) -> None:
        assert _batch_prompt("yes", BATCH_ACTIONS, None) == EXPECTED_PROMPT_BATCH_NO_HISTORY

    def test_batch_prompt_with_history_is_exact(self) -> None:
        assert _batch_prompt("no", BATCH_ACTIONS, HISTORY) == EXPECTED_PROMPT_BATCH_WITH_HISTORY


class TestHistoryBlock:
    """The recent-turns window is context the classifier relies on; every mutation
    here changes the bytes the model sees, so each shape is asserted exactly."""

    def test_empty_histories_render_nothing(self) -> None:
        assert _history_block(None) == ""
        assert _history_block([]) == ""

    def test_turns_render_as_role_content_lines(self) -> None:
        assert _history_block(HISTORY) == "user: hey\nassistant: sure"

    def test_missing_role_and_content_render_empty(self) -> None:
        assert _history_block([{"content": "no role"}, {"role": "user"}, {}]) == (
            ": no role\nuser: \n: "
        )

    def test_a_content_is_clipped_per_turn_not_lost(self) -> None:
        content = "x" * (HIL_CLASSIFIER_MAX_ARG_CHARS + 10)
        assert _history_block([{"role": "user", "content": content}]) == (
            f"user: {clip_text(content, HIL_CLASSIFIER_MAX_ARG_CHARS)}"
        )

    def test_the_total_is_clipped_across_turns(self) -> None:
        big = "y" * (HIL_CLASSIFIER_MAX_DETAIL_CHARS // 2)
        raw = "\n".join(["user: " + big, "assistant: " + big])
        assert _history_block([{"role": "user", "content": big}, {"role": "assistant", "content": big}]) == (
            clip_text(raw, HIL_CLASSIFIER_MAX_DETAIL_CHARS)
        )

    def test_the_exact_boundary_is_not_clipped(self) -> None:
        content = "z" * HIL_CLASSIFIER_MAX_ARG_CHARS
        assert _history_block([{"role": "user", "content": content}]) == f"user: {content}"


class TestInterpretCallContract:
    """The LLM boundary is a mock, so every argument the production code passes to it
    is an observable contract: the schema, the exact prompt, the label, the timeout,
    and the metered silent config. A mutation that drops, Nones, or mangles any of
    them must fail here."""

    async def test_single_classification_passes_the_full_contract(self, resolver: dict) -> None:
        resolver["llm"].return_value = DecisionResult(action="approve")
        result = await interpret_decision_message("yes", [SINGLE_ACTION], None, user_id=USER_ID)

        assert result == DecisionResult(action="approve")
        call = resolver["llm"].await_args
        assert call.args[0] is DecisionResult
        assert call.args[1] == EXPECTED_PROMPT_SINGLE_NO_HISTORY
        assert call.kwargs == {
            "label": "hil_conversational_resolve",
            "timeout": HIL_LLM_TIMEOUT_SECONDS,
            "config": silent_metered_config(USER_ID),
        }

    async def test_single_classification_renders_history_into_the_prompt(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = DecisionResult(action="deny")
        await interpret_decision_message("no", [SINGLE_ACTION], HISTORY, user_id=USER_ID)

        assert resolver["llm"].await_args.args[1] == EXPECTED_PROMPT_SINGLE_WITH_HISTORY

    async def test_batch_classification_passes_the_full_contract(self, resolver: dict) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=False)
        result = await interpret_batch_decision_message(
            "yes", BATCH_ACTIONS, None, user_id=USER_ID
        )

        assert result == BatchDecisionResult(unrelated=False)
        call = resolver["llm"].await_args
        assert call.args[0] is BatchDecisionResult
        assert call.args[1] == EXPECTED_PROMPT_BATCH_NO_HISTORY
        assert call.kwargs == {
            "label": "hil_conversational_resolve_batch",
            "timeout": HIL_LLM_TIMEOUT_SECONDS,
            "config": silent_metered_config(USER_ID),
        }

    async def test_batch_classification_renders_history_into_the_prompt(
        self, resolver: dict
    ) -> None:
        resolver["llm"].return_value = BatchDecisionResult(unrelated=False)
        await interpret_batch_decision_message("no", BATCH_ACTIONS, HISTORY, user_id=USER_ID)

        assert resolver["llm"].await_args.args[1] == EXPECTED_PROMPT_BATCH_WITH_HISTORY

    async def test_single_llm_error_leaves_the_approval_pending_and_logs_exactly(
        self, resolver: dict
    ) -> None:
        resolver["llm"].side_effect = ConnectionError("provider down")
        result = await interpret_decision_message("yes", [SINGLE_ACTION], None, user_id=USER_ID)

        assert result is None
        hil_conversational.log.warning.assert_called_once_with(
            f"{LogTag.HIL} Conversational resolve failed, leaving pending",
            error="provider down",
            error_type="ConnectionError",
        )

    async def test_batch_llm_error_fails_toward_leave_and_logs_exactly(
        self, resolver: dict
    ) -> None:
        resolver["llm"].side_effect = ConnectionError("provider down")
        result = await interpret_batch_decision_message("yes", BATCH_ACTIONS, None, user_id=USER_ID)

        assert result == BatchDecisionResult(unrelated=False)
        assert result.decisions == []
        hil_conversational.log.warning.assert_called_once_with(
            f"{LogTag.HIL} Batch conversational resolve failed, leaving pending",
            error="provider down",
            error_type="ConnectionError",
        )


class TestSafeResolve:
    """``_safe_resolve`` is the one place a decision becomes a durable resolution.
    Its exact call contract (user, scope) and its tolerance for lost races are
    pinned here."""

    async def test_resolution_carries_the_full_decision_contract(self, resolver: dict) -> None:
        await _safe_resolve("appr-9", USER_ID, "deny", "do it tomorrow")

        assert resolver["resolve"].await_args.kwargs == {
            "approval_id": "appr-9",
            "user_id": USER_ID,
            "kind": "deny",
            "feedback": "do it tomorrow",
            "scope": "once",
        }

    async def test_a_forbidden_approval_is_quietly_ignored(self, resolver: dict) -> None:
        # The approval belongs to another user or stream — not ours to touch, and not
        # an error the chat turn should crash on.
        resolver["resolve"].side_effect = ApprovalRequestForbidden()
        await _safe_resolve("appr-9", USER_ID, "approve", None)

    async def test_a_non_approval_error_propagates(self, resolver: dict) -> None:
        # Only the "lost the race" pair is tolerated. Anything else is a real bug and
        # must fail loud, not vanish behind a broad except.
        resolver["resolve"].side_effect = ValueError("boom")
        with pytest.raises(ValueError):
            await _safe_resolve("appr-9", USER_ID, "approve", None)
