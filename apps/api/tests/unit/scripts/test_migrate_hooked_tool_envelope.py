"""The audit of playbook placeholders that read a hooked tool's output."""

import pytest
from scripts.migrate_hooked_tool_envelope import stale_references

HOOKED = frozenset({"TWITTER_RECENT_SEARCH", "GMAIL_GET_CONTACTS"})


def _playbook(*steps: dict[str, object]) -> dict[str, object]:
    return {"steps": list(steps)}


SEARCH = {"id": "search", "tool": "TWITTER_RECENT_SEARCH", "args": {"query": "gaia"}}


@pytest.mark.unit
class TestStaleReferences:
    def test_a_path_into_a_hooked_steps_output_is_reported(self) -> None:
        reader = {"id": "post", "tool": "SLACK_SEND", "args": {"text": "$steps.search.tweets"}}
        assert stale_references(_playbook(SEARCH, reader), HOOKED) == ["$steps.search.tweets"]

    def test_a_reference_embedded_in_text_is_reported(self) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"text": "Found $steps.search.result_count tweets"}}
        assert stale_references(_playbook(SEARCH, reader), HOOKED) == ["$steps.search.result_count"]

    def test_a_for_each_over_a_hooked_output_is_reported(self) -> None:
        loop = {
            "tool": "SLACK_SEND",
            "for_each": "$steps.search.tweets",
            "args": {"t": "$item.text"},
        }
        assert stale_references(_playbook(SEARCH, loop), HOOKED) == ["$steps.search.tweets"]

    def test_a_hooked_tool_run_through_execute_counts(self) -> None:
        via_execute = {
            "id": "people",
            "tool": "execute",
            "args": {"tool_name": "GMAIL_GET_CONTACTS", "data": {}},
        }
        reader = {"tool": "SLACK_SEND", "args": {"to": "$steps.people.contacts"}}
        assert stale_references(_playbook(via_execute, reader), HOOKED) == [
            "$steps.people.contacts"
        ]

    def test_a_hooked_call_inside_a_handoff_counts(self) -> None:
        handoff = {"id": "sub", "handoff": "twitter", "steps": [SEARCH]}
        reader = {"tool": "SLACK_SEND", "args": {"text": "$steps.search.tweets"}}
        assert stale_references(_playbook(handoff, reader), HOOKED) == ["$steps.search.tweets"]

    def test_a_last_run_path_into_a_hooked_tool_is_reported(self) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"since": "$last_run.TWITTER_RECENT_SEARCH.newest"}}
        assert stale_references(_playbook(reader), HOOKED) == [
            "$last_run.TWITTER_RECENT_SEARCH.newest"
        ]

    @pytest.mark.parametrize(
        "text",
        ["$steps.other.items", "$last_run.SLACK_SEND.ts", "$today", "$HOME/search"],
        ids=["unhooked_step", "unhooked_last_run", "other_root", "literal_text"],
    )
    def test_references_that_do_not_read_a_hooked_output_are_ignored(self, text: str) -> None:
        other = {"id": "other", "tool": "SLACK_LIST", "args": {}}
        reader = {"tool": "SLACK_SEND", "args": {"text": text}}
        assert stale_references(_playbook(SEARCH, other, reader), HOOKED) == []

    def test_a_hooked_step_without_an_id_cannot_be_referenced(self) -> None:
        anonymous = {"id": "", "tool": "TWITTER_RECENT_SEARCH", "args": {}}
        reader = {"tool": "SLACK_SEND", "args": {"text": "$steps..tweets"}}
        assert stale_references(_playbook(anonymous, reader), HOOKED) == []

    def test_a_playbook_without_steps_has_nothing_to_report(self) -> None:
        assert stale_references({}, HOOKED) == []
