"""The audit of playbook placeholders that read a hooked tool's output."""

from unittest.mock import patch

import pytest
from scripts.migrate_hooked_tool_envelope import (
    References,
    hooked_tool_inventory,
    old_form_shape_filter,
    playbook_references,
)

from app.utils.composio_hooks.registry import hook_registry

HOOKED = frozenset({"TWITTER_RECENT_SEARCH", "GMAIL_GET_CONTACTS"})


def _playbook(*steps: dict[str, object]) -> dict[str, object]:
    return {"steps": list(steps)}


SEARCH = {"id": "search", "tool": "TWITTER_RECENT_SEARCH", "args": {"query": "gaia"}}


@pytest.mark.unit
class TestStaleReferences:
    def test_a_path_into_a_hooked_steps_output_is_reported(self) -> None:
        reader = {"id": "post", "tool": "SLACK_SEND", "args": {"text": "$steps.search.tweets"}}
        assert playbook_references(_playbook(SEARCH, reader), HOOKED) == References(
            stale=["$steps.search.tweets"], ambiguous=[]
        )

    def test_a_reference_embedded_in_text_is_reported(self) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"text": "Found $steps.search.result_count tweets"}}
        assert playbook_references(_playbook(SEARCH, reader), HOOKED) == References(
            stale=["$steps.search.result_count"], ambiguous=[]
        )

    def test_a_for_each_over_a_hooked_output_is_reported(self) -> None:
        loop = {
            "tool": "SLACK_SEND",
            "for_each": "$steps.search.tweets",
            "args": {"t": "$item.text"},
        }
        assert playbook_references(_playbook(SEARCH, loop), HOOKED) == References(
            stale=["$steps.search.tweets"], ambiguous=[]
        )

    def test_a_hooked_tool_run_through_execute_counts(self) -> None:
        via_execute = {
            "id": "people",
            "tool": "execute",
            "args": {"tool_name": "GMAIL_GET_CONTACTS", "data": {}},
        }
        reader = {"tool": "SLACK_SEND", "args": {"to": "$steps.people.contacts"}}
        assert playbook_references(_playbook(via_execute, reader), HOOKED) == References(
            stale=["$steps.people.contacts"], ambiguous=[]
        )

    def test_a_hooked_call_inside_a_handoff_counts(self) -> None:
        handoff = {"id": "sub", "handoff": "twitter", "steps": [SEARCH]}
        reader = {"tool": "SLACK_SEND", "args": {"text": "$steps.search.tweets"}}
        assert playbook_references(_playbook(handoff, reader), HOOKED) == References(
            stale=["$steps.search.tweets"], ambiguous=[]
        )

    def test_a_last_run_path_into_a_hooked_tool_is_reported(self) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"since": "$last_run.TWITTER_RECENT_SEARCH.newest"}}
        assert playbook_references(_playbook(reader), HOOKED) == References(
            stale=["$last_run.TWITTER_RECENT_SEARCH.newest"], ambiguous=[]
        )

    @pytest.mark.parametrize(
        "text",
        ["$steps.other.items", "$last_run.SLACK_SEND.ts", "$today", "$HOME/search"],
        ids=["unhooked_step", "unhooked_last_run", "other_root", "literal_text"],
    )
    def test_references_that_do_not_read_a_hooked_output_are_ignored(self, text: str) -> None:
        other = {"id": "other", "tool": "SLACK_LIST", "args": {}}
        reader = {"tool": "SLACK_SEND", "args": {"text": text}}
        assert playbook_references(_playbook(SEARCH, other, reader), HOOKED) == References(
            stale=[], ambiguous=[]
        )

    @pytest.mark.parametrize(
        "text",
        ["$steps.search.successful", "$steps.search.error"],
        ids=["success_flag", "error_text"],
    )
    def test_a_read_of_the_envelopes_own_flags_is_fine(self, text: str) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"text": text}}
        assert playbook_references(_playbook(SEARCH, reader), HOOKED) == References([], [])

    @pytest.mark.parametrize(
        "text",
        ["$steps.search.data.tweets", "$last_run.TWITTER_RECENT_SEARCH.data.newest"],
        ids=["step", "last_run"],
    )
    def test_a_data_path_is_left_for_a_person_to_check(self, text: str) -> None:
        """Already migrated, or an old read of a raw data field: nothing offline tells them apart."""
        reader = {"tool": "SLACK_SEND", "args": {"text": text}}
        assert playbook_references(_playbook(SEARCH, reader), HOOKED) == References([], [text])

    def test_a_whole_value_reference_now_gets_the_envelope_and_is_reported(self) -> None:
        reader = {"tool": "SLACK_SEND", "args": {"payload": "$steps.search"}}
        assert playbook_references(_playbook(SEARCH, reader), HOOKED) == References(
            stale=["$steps.search"], ambiguous=[]
        )

    def test_a_hooked_step_without_an_id_cannot_be_referenced(self) -> None:
        anonymous = {"id": "", "tool": "TWITTER_RECENT_SEARCH", "args": {}}
        reader = {"tool": "SLACK_SEND", "args": {"text": "$steps..tweets"}}
        assert playbook_references(_playbook(anonymous, reader), HOOKED) == References(
            stale=[], ambiguous=[]
        )

    def test_a_playbook_without_steps_has_nothing_to_report(self) -> None:
        assert playbook_references({}, HOOKED) == References(stale=[], ambiguous=[])


@pytest.mark.unit
class TestHookedToolInventory:
    def test_the_inventory_is_the_registrys_tool_scoped_hooks(self) -> None:
        with (
            patch.object(hook_registry, "after_hook_tools", {"TWITTER_RECENT_SEARCH"}),
            patch.object(hook_registry, "has_broad_after_hook", False),
        ):
            assert hooked_tool_inventory() == frozenset({"TWITTER_RECENT_SEARCH"})

    def test_a_toolkit_wide_hook_stops_the_audit(self) -> None:
        with patch.object(hook_registry, "has_broad_after_hook", True):
            with pytest.raises(SystemExit, match="scoped by toolkit or to every tool"):
                hooked_tool_inventory()


@pytest.mark.unit
class TestOldFormShapeFilter:
    def test_only_catalog_shapes_learned_before_the_envelope_match(self) -> None:
        assert old_form_shape_filter(HOOKED) == {
            "scope": "global",
            "tool_name": {"$in": ["GMAIL_GET_CONTACTS", "TWITTER_RECENT_SEARCH"]},
            "output_schema.properties.successful": {"$exists": False},
        }
