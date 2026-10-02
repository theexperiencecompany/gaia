"""The delivery instructions comms writes a tracked todo run's result under."""

import pytest

from app.agents.prompts.comms_prompts import tracked_todo_delivery_note
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.comms import SILENCE_DIRECTIVE
from app.constants.general import NEW_MESSAGE_BREAKER

pytestmark = pytest.mark.unit


def _note() -> str:
    # Built per test, not at import: mutmut only credits a test with code it runs.
    return tracked_todo_delivery_note("Watch the deploy", None, None)


class TestTrackedTodoDeliveryNote:
    def test_the_whole_instruction_is_pinned(self) -> None:
        """Every sentence is a rule comms follows; an edit here changes what users are sent."""
        assert (
            wrap_agent_payload(
                AgentTag.DELIVERY_INSTRUCTIONS,
                "This is the result of a background run of the user's tracked todo \"Watch the "
                'deploy". Nobody asked for it just now: it ran on its schedule or on an event it '
                "watches, and its full record is already kept in the todo. Message the user when "
                "the report shows something new they need to know or act on, a decision or "
                "blocker only they can settle that they have not already been asked about, or a "
                "result they asked to hear every time (always send that one). Anything else is "
                "not worth a message: a routine check, a no-op, nothing new, a question they "
                "already have, a run that only kept notes. Then reply with exactly one line and "
                f"nothing else: {SILENCE_DIRECTIVE}. "
                "There is no message of theirs to react to, so never answer with a reaction. When "
                "you do write, it reaches their chat app as plain text with no cards: lead with "
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

    def test_it_offers_silence_in_the_parsers_own_format(self) -> None:
        assert SILENCE_DIRECTIVE in _note()

    def test_it_rules_out_a_reaction_and_splits_on_the_real_separator(self) -> None:
        assert "never answer with a reaction" in _note()
        assert f"Split with {NEW_MESSAGE_BREAKER} only when" in _note()

    def test_it_says_when_a_message_is_worth_sending(self) -> None:
        assert "a result they asked to hear every time (always send that one)" in _note()
        assert "a question they already have" in _note()
        assert "never promise to follow up later" in _note()

    def test_the_todos_standing_rules_close_the_note_and_bind_it(self) -> None:
        """Regression: an Inbox desk briefing with content was silenced as routine under a rule to deliver every one."""
        note = tracked_todo_delivery_note("Word count", "- Tell me the result every time.", None)

        assert (
            "only when there is more than one beat.\n"
            "Its Standing rules, the user's own instructions for this todo. They bind this "
            "decision above every default here and in your instructions, the SILENCE rule "
            "included: when one asks to hear this todo's results, a report with content is "
            "sent, whole, and SILENCE is only for a report with nothing in it.\n"
            "- Tell me the result every time.\n"
        ) in note

    def test_key_details_follow_the_rules_as_details_of_their_own(self) -> None:
        note = tracked_todo_delivery_note("Word count", "- Be brief.", "- tell me every time")

        assert (
            "- Be brief.\nIts Key Details, which can also hold a request of theirs:\n"
            "- tell me every time\n"
        ) in note
        assert note.index("Message the user when") < note.index("- Be brief.")
