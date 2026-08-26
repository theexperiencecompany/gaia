"""Unit tests for deadline-anchored creation routing.

The regex nudge must fire on "remind/check ... N <units> before X" requests and
stay silent on plain relative reminders, so the executor routes the former to
create_tracked_todo (due_date = deadline) instead of a one-shot reminder.
"""

from langchain_core.messages import HumanMessage
import pytest

from app.agents.prompts.todo_prompts import (
    DEADLINE_ROUTING_NUDGE,
    TODO_SYSTEM_PROMPT,
    deadline_routing_nudge,
)
from app.agents.tools.todo_tools import _latest_human_text, create_todo_pre_model_hook


class TestLatestHumanText:
    def _msg(self, kind: str, content: object):
        if kind == "human":
            return HumanMessage(content=content)
        from langchain_core.messages import AIMessage

        return AIMessage(content=content)

    def test_returns_the_most_recent_human_message_not_the_first(self):
        messages = [
            self._msg("human", "older question"),
            self._msg("ai", "answer"),
            self._msg("human", "Remind me 3 days before my visa appointment"),
        ]
        assert _latest_human_text(messages) == "Remind me 3 days before my visa appointment"

    def test_skips_non_human_messages_scanning_backwards(self):
        messages = [
            self._msg("human", "the real request"),
            self._msg("ai", "a later reply"),
        ]
        assert _latest_human_text(messages) == "the real request"

    def test_no_human_message_yields_none(self):
        assert _latest_human_text([self._msg("ai", "hi")]) is None
        assert _latest_human_text([]) is None

    def test_empty_string_content_is_none_not_empty(self):
        assert _latest_human_text([HumanMessage(content="")]) is None

    def test_string_parts_of_content_blocks_are_joined(self):
        content = ["check", "my documents"]
        assert _latest_human_text([HumanMessage(content=content)]) == "check my documents"

    def test_dict_content_blocks_contribute_their_text_field(self):
        content = [{"type": "text", "text": "before"}, {"type": "image_url", "image_url": "x"}]
        assert _latest_human_text([HumanMessage(content=content)]) == "before"

    def test_all_empty_content_blocks_are_none(self):
        content = [{"type": "text", "text": ""}]
        assert _latest_human_text([HumanMessage(content=content)]) is None


class TestDeadlineRoutingNudge:
    @pytest.mark.parametrize(
        ("text", "matches"),
        [
            ("Remind me 3 days before my visa appointment", True),
            ("remind me two weeks prior to the filing date", True),
            ("Check my documents a week ahead of the interview", True),
            ("Follow up 1 month before the lease ends", True),
            ("Notify me 24 hours before the flight departs", True),
            ("Renew my passport before my visa appointment", False),
            ("Remind me in 10 minutes to join the call", False),
            ("Remind me tomorrow at 9 AM", False),
            ("Before I forget, send that email", False),
        ],
    )
    def test_pattern_matches_only_deadline_anchored_requests(self, text: str, matches: bool):
        nudge = deadline_routing_nudge(text)
        if matches:
            assert nudge == DEADLINE_ROUTING_NUDGE
        else:
            assert nudge == ""

    def test_none_text_yields_no_nudge(self):
        assert deadline_routing_nudge(None) == ""

    def test_empty_text_yields_no_nudge(self):
        assert deadline_routing_nudge("") == ""


class TestSystemPromptTeachesRouting:
    def test_prompt_names_due_date_vs_scheduled_at(self):
        assert "due_date" in TODO_SYSTEM_PROMPT
        assert "scheduled_at" in TODO_SYSTEM_PROMPT
        assert "NOT reminders" in TODO_SYSTEM_PROMPT

    def test_prompt_carries_two_contrasting_examples(self):
        assert "create_tracked_todo" in TODO_SYSTEM_PROMPT
        assert "delay_seconds=600" in TODO_SYSTEM_PROMPT


class TestPreModelHookNudge:
    def _state(self, *messages: str) -> dict:
        return {"messages": [HumanMessage(content=m) for m in messages]}

    def test_deadline_anchored_message_injects_the_nudge(self):
        hook = create_todo_pre_model_hook(source="executor")
        result = hook(
            self._state("Remind me 3 days before my visa appointment"),
            config={},
            store=None,
        )
        injected = result["messages"][-1].content
        assert "ROUTING NOTE" in injected

    def test_plain_reminder_message_does_not_inject_the_nudge(self):
        hook = create_todo_pre_model_hook(source="executor")
        result = hook(self._state("Remind me in 10 minutes"), config={}, store=None)
        injected = result["messages"][-1].content
        assert "ROUTING NOTE" not in injected
