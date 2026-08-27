"""Tests for app.services.browser.captions — caption_from_action_list, describe_action, et al.

Covers every action name branch in describe_action with exact expected strings
from source, plus the two caption builders and _dedupe_join.
"""

from __future__ import annotations

import pytest

from app.schemas.browser import BrowserAction
from app.services.browser.captions import (
    _dedupe_join,
    caption_from_action_list,
    describe_action,
)

# ---------------------------------------------------------------------------
# describe_action — every named branch, exact strings from source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDescribeAction:
    def test_navigate_with_www_host(self):
        assert (
            describe_action("navigate", {"url": "https://www.example.com/path"})
            == "Opening example.com"
        )

    def test_navigate_without_www(self):
        assert (
            describe_action("navigate", {"url": "https://example.com/search"})
            == "Opening example.com"
        )

    def test_navigate_subdomain(self):
        assert (
            describe_action("navigate", {"url": "https://sub.example.com/"})
            == "Opening sub.example.com"
        )

    def test_navigate_with_port_and_path(self):
        assert (
            describe_action("navigate", {"url": "https://sub.example.com:8080/foo?x=1"})
            == "Opening sub.example.com"
        )

    def test_navigate_empty_url(self):
        assert describe_action("navigate", {"url": ""}) == "Opening the page"

    def test_navigate_missing_url(self):
        assert describe_action("navigate", {}) == "Opening the page"

    def test_navigate_none_url(self):
        assert describe_action("navigate", {"url": None}) == "Opening the page"

    def test_navigate_invalid_url_no_hostname(self):
        assert describe_action("navigate", {"url": "not-a-url"}) == "Opening the page"

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_with_query(self, name):
        assert describe_action(name, {"query": "hello world"}) == 'Searching "hello world"'

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_with_text_fallback(self, name):
        assert describe_action(name, {"text": "fallback query"}) == 'Searching "fallback query"'

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_query_precedence_over_text(self, name):
        assert describe_action(name, {"query": "q", "text": "t"}) == 'Searching "q"'

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_empty(self, name):
        assert describe_action(name, {}) == "Searching"

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_whitespace_only(self, name):
        assert describe_action(name, {"query": "   "}) == "Searching"

    @pytest.mark.parametrize("name", ["search", "search_page"])
    def test_search_trims_whitespace(self, name):
        assert describe_action(name, {"query": "  hello world  "}) == 'Searching "hello world"'

    def test_search_query_none_falls_back_to_text(self):
        assert describe_action("search", {"query": None, "text": "t"}) == 'Searching "t"'

    def test_search_query_none_and_text_none(self):
        assert describe_action("search", {"query": None, "text": None}) == "Searching"

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_with_text(self, name):
        assert describe_action(name, {"text": "my value"}) == 'Typing "my value"'

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_trims_whitespace(self, name):
        assert describe_action(name, {"text": "  hello  "}) == 'Typing "hello"'

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_empty_text(self, name):
        assert describe_action(name, {"text": ""}) == "Typing"

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_whitespace_only(self, name):
        assert describe_action(name, {"text": "   "}) == "Typing"

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_none_text(self, name):
        assert describe_action(name, {"text": None}) == "Typing"

    @pytest.mark.parametrize("name", ["input", "send_keys"])
    def test_input_missing_text(self, name):
        assert describe_action(name, {}) == "Typing"

    def test_select_dropdown_with_text(self):
        assert describe_action("select_dropdown", {"text": "Option A"}) == 'Choosing "Option A"'

    def test_select_dropdown_trims_whitespace(self):
        assert describe_action("select_dropdown", {"text": "  Option A  "}) == 'Choosing "Option A"'

    def test_select_dropdown_empty(self):
        assert describe_action("select_dropdown", {"text": ""}) == "Choosing an option"

    def test_select_dropdown_whitespace(self):
        assert describe_action("select_dropdown", {"text": "   "}) == "Choosing an option"

    def test_select_dropdown_none(self):
        assert describe_action("select_dropdown", {"text": None}) == "Choosing an option"

    def test_select_dropdown_missing(self):
        assert describe_action("select_dropdown", {}) == "Choosing an option"

    def test_click(self):
        assert describe_action("click", {}) == "Clicking"

    def test_click_ignores_params(self):
        assert describe_action("click", {"text": "ignored", "x": 1}) == "Clicking"

    @pytest.mark.parametrize("name", ["scroll", "scroll_to_text"])
    def test_scroll(self, name):
        assert describe_action(name, {}) == "Scrolling"

    @pytest.mark.parametrize(
        "name", ["extract", "read_file", "read_long_content", "find_text", "find_elements"]
    )
    def test_read_actions(self, name):
        assert describe_action(name, {}) == "Reading the page"

    def test_upload_file(self):
        assert describe_action("upload_file", {}) == "Uploading a file"

    def test_go_back(self):
        assert describe_action("go_back", {}) == "Going back"

    def test_wait(self):
        assert describe_action("wait", {}) == "Waiting for the page"

    @pytest.mark.parametrize("name", ["request_human_takeover", "solve_captcha_with_help"])
    def test_handover(self, name):
        assert describe_action(name, {}) == "Handing this step to you"

    def test_done(self):
        assert describe_action("done", {}) == "Wrapping up"

    def test_fallback_replaces_underscores(self):
        assert describe_action("my_custom_action", {}) == "my custom action"

    def test_fallback_single_word(self):
        assert describe_action("unknown", {}) == "unknown"

    def test_fallback_multiple_underscores(self):
        assert describe_action("a_b_c_d", {}) == "a b c d"


# ---------------------------------------------------------------------------
# _dedupe_join
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDedupeJoin:
    def test_empty(self):
        assert _dedupe_join([]) == ""

    def test_single(self):
        assert _dedupe_join(["Clicking"]) == "Clicking"

    def test_no_duplicates(self):
        assert _dedupe_join(["Clicking", "Scrolling"]) == "Clicking, Scrolling"

    def test_consecutive_duplicates(self):
        assert _dedupe_join(["Clicking", "Clicking"]) == "Clicking"

    def test_non_consecutive_duplicates_still_deduped(self):
        assert _dedupe_join(["Clicking", "Scrolling", "Clicking"]) == "Clicking, Scrolling"

    def test_filters_empty_strings(self):
        assert _dedupe_join(["", "Clicking", ""]) == "Clicking"

    def test_all_empty(self):
        assert _dedupe_join(["", ""]) == ""

    def test_order_preserved(self):
        assert _dedupe_join(["A", "B", "C"]) == "A, B, C"

    def test_preserves_first_occurrence(self):
        assert _dedupe_join(["B", "A", "B", "A"]) == "B, A"


# ---------------------------------------------------------------------------
# caption_from_action_list — a step snapshot's structured actions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaptionFromActionList:
    def test_empty(self):
        assert caption_from_action_list([]) == ""

    def test_single_click(self):
        assert caption_from_action_list([BrowserAction(name="click")]) == "Clicking"

    def test_navigate_names_the_host(self):
        """The whole point of structured actions: params survive, so the caption
        says which site was opened instead of a generic phrase."""
        actions = [BrowserAction(name="navigate", inputs={"url": "https://www.github.com/x"})]
        assert caption_from_action_list(actions) == "Opening github.com"

    def test_typing_quotes_the_text(self):
        actions = [BrowserAction(name="input", inputs={"text": "hello"})]
        assert caption_from_action_list(actions) == 'Typing "hello"'

    def test_consecutive_repeats_collapse(self):
        actions = [BrowserAction(name="click"), BrowserAction(name="click")]
        assert caption_from_action_list(actions) == "Clicking"

    def test_distinct_actions_join(self):
        actions = [BrowserAction(name="click"), BrowserAction(name="scroll")]
        assert caption_from_action_list(actions) == "Clicking, Scrolling"

    def test_unknown_action_uses_fallback(self):
        assert caption_from_action_list([BrowserAction(name="my_custom_action")]) == (
            "my custom action"
        )

    def test_click_names_the_element_it_hit(self):
        """A bare "Clicking" tells a reader nothing. The element's own name is
        what makes the step readable — and it is grounded in the page, not in
        the model's claim about its intent."""
        actions = [BrowserAction(name="click", inputs={"index": 9}, target="Add to cart")]
        assert caption_from_action_list(actions) == 'Clicking "Add to cart"'

    def test_click_without_a_target_names_the_coordinates(self):
        actions = [
            BrowserAction(name="click", inputs={"coordinate_x": 412, "coordinate_y": 680})
        ]
        assert caption_from_action_list(actions) == "Clicking at 412, 680"

    def test_click_with_neither_falls_back_to_the_verb(self):
        assert caption_from_action_list([BrowserAction(name="click")]) == "Clicking"

    def test_typing_names_the_field(self):
        actions = [
            BrowserAction(name="input", inputs={"text": "Aryan"}, target="Full name")
        ]
        assert caption_from_action_list(actions) == 'Typing "Aryan" into "Full name"'

    def test_long_target_is_truncated(self):
        actions = [BrowserAction(name="click", inputs={}, target="x" * 80)]
        caption = caption_from_action_list(actions)
        assert caption.endswith('…"')
        assert len(caption) < 60
