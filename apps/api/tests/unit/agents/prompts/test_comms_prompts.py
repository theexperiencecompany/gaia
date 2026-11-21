"""The delivery instructions comms writes a tracked todo run's result under."""

import pytest

from app.agents.prompts.comms_prompts import outcome_delivery_note, tracked_todo_delivery_note
from app.constants.agents import AgentTag, OutcomeState, wrap_agent_payload
from app.constants.comms import STAY_SILENT_TOOL_NAME
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER

pytestmark = pytest.mark.unit


def _note() -> str:
    # Built per test, not at import: mutmut only credits a test with code it runs.
    return tracked_todo_delivery_note(
        "Watch the deploy", None, None, runs_once=False, run_history=()
    )


class TestTrackedTodoDeliveryNote:
    def test_a_todo_that_runs_once_always_sends_its_answer(self) -> None:
        """A one-time check the user asked for was silenced 10/10 when its answer was 'no'."""
        once = tracked_todo_delivery_note(
            "Umbrella check", None, None, runs_once=True, run_history=()
        )

        assert (
            "This todo runs once, to answer what the user asked when they set it up, so its "
            "result is that answer and they are waiting for it: always send it, even when the "
            "answer is no or nothing to worry about. "
        ) in once
        assert "Write it up: lead with what changed" in once
        assert "When you do write" not in once
        assert "Nobody asked for it just now" not in once
        assert STAY_SILENT_TOOL_NAME not in once
        assert "not worth a message" not in once

    @pytest.mark.regression
    def test_a_todo_that_runs_once_never_answers_with_a_reaction(self) -> None:
        """A reaction is an invalid directive for a todo run, so the awaited answer was dropped."""
        once = tracked_todo_delivery_note(
            "Umbrella check", None, None, runs_once=True, run_history=()
        )

        assert (
            "There is no message of theirs to react to, so never answer with a reaction."
        ) in once

    def test_the_whole_instruction_is_pinned(self) -> None:
        """Every sentence is a rule comms follows; an edit here changes what users are sent."""
        assert (
            wrap_agent_payload(
                AgentTag.DELIVERY_INSTRUCTIONS,
                "This is the result of a background run of the user's tracked todo \"Watch the "
                'deploy". The run cannot message the user: only you reach them, so nothing in its '
                "report is something they have seen. Nothing from this todo has reached them yet. "
                "Nobody asked for it just now: it ran on its schedule or on an event it "
                "watches, and its full record is already kept in the todo. Message the user when "
                "the report shows something new they need to know or act on, a decision or "
                "blocker only they can settle that they have not already been asked about, a "
                "result they asked to hear every time (always send that one), or the nudge or "
                "reminder this todo exists to give, even when it repeats the last one. Anything "
                "else is "
                "not worth a message: a routine check, a no-op, nothing new, a question they "
                "already have, open items you already raised that are still open (a reply they "
                "owe, an approval they have not given), a run that only kept notes. A report that "
                "says only that nothing is new is that too: a mail-woken run with nothing to "
                "escalate, or a run held for quiet hours, says exactly that, and the next briefing "
                f"carries the rest. Then call {STAY_SILENT_TOOL_NAME} and write no text. "
                "Decide first and do only one of the two: a message, or the call alone, never a "
                "recap of open items beside it. "
                "There is no message of theirs to react to, so never answer with a reaction. When "
                "you do write, lead with "
                "what changed or what they must decide, give the concrete details they need, keep "
                "it short, never mention runs, schedules or internal ids, and never promise to "
                f"follow up later. Split with {NEW_MESSAGE_BREAKER} only when there is more than "
                "one beat.",
            )
            == _note()
        )

    def test_it_is_a_delivery_instruction_naming_the_todo(self) -> None:
        assert _note().startswith(f"<{AgentTag.DELIVERY_INSTRUCTIONS}>")
        assert _note().rstrip().endswith(f"</{AgentTag.DELIVERY_INSTRUCTIONS}>")
        assert 'tracked todo "Watch the deploy"' in _note()

    def test_it_offers_silence_as_the_tool_the_graph_ends_on(self) -> None:
        assert f"call {STAY_SILENT_TOOL_NAME} and write no text" in _note()

    def test_it_rules_out_a_reaction_and_splits_on_the_real_separator(self) -> None:
        assert "never answer with a reaction" in _note()
        assert f"Split with {NEW_MESSAGE_BREAKER} only when" in _note()

    def test_it_says_when_a_message_is_worth_sending(self) -> None:
        assert "a result they asked to hear every time (always send that one)" in _note()
        assert "a question they already have" in _note()
        assert "never promise to follow up later" in _note()

    def test_the_todos_standing_rules_close_the_note_and_bind_it(self) -> None:
        """Regression: an Inbox desk briefing with content was silenced as routine under a rule to deliver every one."""
        note = tracked_todo_delivery_note(
            "Word count",
            "- Tell me the result every time.",
            None,
            runs_once=False,
            run_history=(),
        )

        assert (
            "only when there is more than one beat.\n"
            "Its Standing rules, the user's own instructions for this todo. They bind this "
            f"decision above every default here and in your instructions, the {STAY_SILENT_TOOL_NAME} rule "
            "included: when one asks to hear this todo's results, a report with content is "
            "sent whole, as a long-form deliverable: its headings and line items as written, "
            "in its order, with at most one line of your own before it, never retold as prose "
            f"and never shortened. {STAY_SILENT_TOOL_NAME} is only for a report with nothing in it.\n"
            "- Tell me the result every time.\n"
        ) in note

    def test_a_quiet_hours_nothing_new_is_silence_not_an_alert(self) -> None:
        note = tracked_todo_delivery_note("Inbox desk", None, None, runs_once=False, run_history=())

        assert "A report that says only that nothing is new is that too" in note
        assert "the next briefing carries the rest" in note

    def test_key_details_follow_the_rules_as_details_of_their_own(self) -> None:
        note = tracked_todo_delivery_note(
            "Word count",
            "- Be brief.",
            "- tell me every time",
            runs_once=False,
            run_history=(),
        )

        assert (
            "- Be brief.\nIts Key Details, which can also hold a request of theirs:\n"
            "- tell me every time\n"
        ) in note
        assert note.index("Message the user when") < note.index("- Be brief.")


class TestTheNarratorKnowsWhatReachedTheUser:
    """Seen live: a nudge todo's report said "reminder issued"; comms took it as sent and kept quiet."""

    def test_it_is_told_the_run_cannot_message_the_user(self) -> None:
        note = tracked_todo_delivery_note("Call dad", None, None, runs_once=False, run_history=())
        assert "The run cannot message the user" in note

    def test_gaias_record_of_earlier_runs_is_in_front_of_it(self) -> None:
        history = [
            "- 2026-11-05T06:30:00+00:00 [run_finished] run r1: sent: call dad today",
            "- 2026-11-06T06:32:00+00:00 [run_finished] run r2: kept quiet: routine",
        ]
        note = tracked_todo_delivery_note(
            "Call dad", None, None, runs_once=False, run_history=history
        )
        assert (
            "GAIA's own record of what this todo's last runs did with their message:\n"
            f"{history[0]}\n{history[1]}\n"
        ) in note

    def test_with_no_earlier_runs_it_knows_nothing_has_reached_them(self) -> None:
        note = tracked_todo_delivery_note("Call dad", None, None, runs_once=False, run_history=())
        assert "Nothing from this todo has reached them yet" in note

    def test_a_nudge_the_todo_exists_to_give_is_worth_repeating(self) -> None:
        note = tracked_todo_delivery_note("Call dad", None, None, runs_once=False, run_history=())
        assert "even when it repeats the last one" in note


class TestTheOutcomeLineCommsNarratesUnder:
    def test_a_plain_text_stop_that_broke_no_rule_adds_nothing(self) -> None:
        assert outcome_delivery_note(None, None) == ""

    def test_a_verified_outcome_gets_its_reply_shape(self) -> None:
        assert outcome_delivery_note(OutcomeState.BLOCKED, None) == (
            "\n\n<delivery_instructions>\nOutcome: blocked. Say plainly what did not happen "
            "and the smallest thing needed from them.\n</delivery_instructions>\n"
        )

    @pytest.mark.parametrize("declared", [OutcomeState.DONE, None])
    def test_an_unbacked_claim_is_reported_as_not_verified(
        self, declared: OutcomeState | None
    ) -> None:
        assert outcome_delivery_note(declared, "no work call succeeded") == (
            "\n\n<delivery_instructions>\nOutcome: NOT verified (no work call succeeded). "
            "Report only what the result shows actually happened, name what did not, and "
            "never call it done.\n</delivery_instructions>\n"
        )
