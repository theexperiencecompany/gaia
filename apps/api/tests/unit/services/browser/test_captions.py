"""Tests for app.services.browser.captions — caption_from_action_summary, describe_action, et al.

Covers every action name branch in describe_action with exact expected strings
from source, plus the two caption builders and _dedupe_join.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.browser.captions import (
    _dedupe_join,
    caption_from_action_summary,
    caption_from_actions,
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
# caption_from_action_summary — flattened "name(params); name(params)" string
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaptionFromActionSummary:
    def test_none(self):
        assert caption_from_action_summary(None) == ""

    def test_empty_string(self):
        assert caption_from_action_summary("") == ""

    def test_whitespace_only(self):
        assert caption_from_action_summary("   ") == ""

    def test_single_click(self):
        assert caption_from_action_summary("click") == "Clicking"

    def test_single_click_with_params(self):
        assert caption_from_action_summary('click({"x": 1})') == "Clicking"

    def test_navigate_without_params_is_opening_the_page(self):
        assert caption_from_action_summary("navigate") == "Opening the page"

    def test_navigate_with_url_still_opening_the_page(self):
        assert caption_from_action_summary("navigate(https://example.com)") == "Opening the page"

    def test_typing_without_text_is_generic(self):
        assert caption_from_action_summary("input") == "Typing"

    def test_search_without_query_is_generic(self):
        assert caption_from_action_summary("search") == "Searching"

    def test_select_dropdown_generic(self):
        assert caption_from_action_summary("select_dropdown") == "Choosing an option"

    def test_scroll(self):
        assert caption_from_action_summary("scroll") == "Scrolling"

    def test_extract(self):
        assert caption_from_action_summary("extract") == "Reading the page"

    def test_upload_file(self):
        assert caption_from_action_summary("upload_file") == "Uploading a file"

    def test_go_back(self):
        assert caption_from_action_summary("go_back") == "Going back"

    def test_wait(self):
        assert caption_from_action_summary("wait") == "Waiting for the page"

    def test_request_human_takeover(self):
        assert caption_from_action_summary("request_human_takeover") == "Handing this step to you"

    def test_solve_captcha_with_help(self):
        assert caption_from_action_summary("solve_captcha_with_help") == "Handing this step to you"

    def test_done(self):
        assert caption_from_action_summary("done") == "Wrapping up"

    def test_unknown_action_uses_fallback(self):
        assert caption_from_action_summary("my_custom_action") == "my custom action"

    def test_multiple_actions_joined(self):
        assert (
            caption_from_action_summary("click; scroll; go_back")
            == "Clicking, Scrolling, Going back"
        )

    def test_multiple_with_params(self):
        result = caption_from_action_summary("navigate(https://x); click({}); input(text)")
        assert result == "Opening the page, Clicking, Typing"

    def test_deduplicates_consecutive(self):
        assert caption_from_action_summary("click; click") == "Clicking"

    def test_deduplicates_non_consecutive_via_dict_keys(self):
        assert caption_from_action_summary("click; scroll; click") == "Clicking, Scrolling"

    def test_filters_empty_parts(self):
        assert caption_from_action_summary("click;  ; scroll") == "Clicking, Scrolling"

    def test_trailing_semicolon(self):
        assert caption_from_action_summary("click;") == "Clicking"

    def test_leading_semicolon(self):
        assert caption_from_action_summary("; click") == "Clicking"

    def test_semicolon_with_spaces(self):
        assert caption_from_action_summary(" click ; scroll ") == "Clicking, Scrolling"

    def test_parentheses_in_params_do_not_break_name(self):
        assert caption_from_action_summary("click((nested))") == "Clicking"

    def test_read_variants(self):
        for name in ("extract", "read_file", "read_long_content", "find_text", "find_elements"):
            assert caption_from_action_summary(name) == "Reading the page"

    def test_all_action_types_full_sweep(self):
        expected = {
            "click": "Clicking",
            "scroll": "Scrolling",
            "scroll_to_text": "Scrolling",
            "extract": "Reading the page",
            "read_file": "Reading the page",
            "read_long_content": "Reading the page",
            "find_text": "Reading the page",
            "find_elements": "Reading the page",
            "upload_file": "Uploading a file",
            "go_back": "Going back",
            "wait": "Waiting for the page",
            "request_human_takeover": "Handing this step to you",
            "solve_captcha_with_help": "Handing this step to you",
            "done": "Wrapping up",
            "input": "Typing",
            "send_keys": "Typing",
            "select_dropdown": "Choosing an option",
            "search": "Searching",
            "search_page": "Searching",
            "navigate": "Opening the page",
        }
        for name, want in expected.items():
            assert caption_from_action_summary(name) == want, f"mismatch for {name}"

    def test_click_and_typing_and_select_mixed(self):
        result = caption_from_action_summary("click; input; select_dropdown")
        assert result == "Clicking, Typing, Choosing an option"

    def test_handoff_mixed(self):
        assert (
            caption_from_action_summary("request_human_takeover(); done()")
            == "Handing this step to you, Wrapping up"
        )


# ---------------------------------------------------------------------------
# caption_from_actions — structured AgentOutput path
# ---------------------------------------------------------------------------


class _FakeAction:
    def __init__(self, name: str, params: dict):
        self._name = name
        self._params = params

    def model_dump(self, exclude_none: bool = False):
        return {self._name: self._params}


class _FakeActionNonDictParams:
    def model_dump(self, exclude_none: bool = False):
        return {"click": "not-a-dict"}


class _FakeActionNoDump:
    pass


class _FakeOutput:
    def __init__(self, actions):
        self.action = actions


@pytest.mark.unit
class TestCaptionFromActions:
    def test_no_action_attribute(self):
        class Empty:
            pass

        assert caption_from_actions(Empty()) == ""

    def test_action_none(self):
        out = _FakeOutput(None)
        assert caption_from_actions(out) == ""

    def test_action_empty_list(self):
        assert caption_from_actions(_FakeOutput([])) == ""

    def test_single_click(self):
        out = _FakeOutput([_FakeAction("click", {})])
        assert caption_from_actions(out) == "Clicking"

    def test_navigate_with_url_uses_host(self):
        out = _FakeOutput([_FakeAction("navigate", {"url": "https://www.example.com/page"})])
        assert caption_from_actions(out) == "Opening example.com"

    def test_navigate_without_url(self):
        out = _FakeOutput([_FakeAction("navigate", {})])
        assert caption_from_actions(out) == "Opening the page"

    def test_navigate_with_www_stripped(self):
        out = _FakeOutput([_FakeAction("navigate", {"url": "https://www.test.com"})])
        assert caption_from_actions(out) == "Opening test.com"

    def test_input_with_text(self):
        out = _FakeOutput([_FakeAction("input", {"text": "hello"})])
        assert caption_from_actions(out) == 'Typing "hello"'

    def test_input_empty_text(self):
        out = _FakeOutput([_FakeAction("input", {"text": ""})])
        assert caption_from_actions(out) == "Typing"

    def test_select_dropdown_with_text(self):
        out = _FakeOutput([_FakeAction("select_dropdown", {"text": "Pick me"})])
        assert caption_from_actions(out) == 'Choosing "Pick me"'

    def test_search_with_query(self):
        out = _FakeOutput([_FakeAction("search", {"query": "cats"})])
        assert caption_from_actions(out) == 'Searching "cats"'

    def test_search_page_with_text(self):
        out = _FakeOutput([_FakeAction("search_page", {"text": "dogs"})])
        assert caption_from_actions(out) == 'Searching "dogs"'

    def test_multiple_actions_joined(self):
        out = _FakeOutput([_FakeAction("click", {}), _FakeAction("scroll", {})])
        assert caption_from_actions(out) == "Clicking, Scrolling"

    def test_single_action_with_multiple_keys(self):
        class MultiAction:
            def model_dump(self, exclude_none: bool = False):
                return {"click": {}, "scroll": {}}

        out = _FakeOutput([MultiAction()])
        result = caption_from_actions(out)
        assert "Clicking" in result
        assert "Scrolling" in result

    def test_non_dict_params_treated_as_empty(self):
        out = _FakeOutput([_FakeActionNonDictParams()])
        assert caption_from_actions(out) == "Clicking"

    def test_no_model_dump_returns_empty(self):
        out = _FakeOutput([_FakeActionNoDump()])
        assert caption_from_actions(out) == ""

    def test_deduplicates(self):
        out = _FakeOutput([_FakeAction("click", {}), _FakeAction("click", {})])
        assert caption_from_actions(out) == "Clicking"

    def test_magic_mock_action_filters_empty_dump(self):
        empty = MagicMock()
        empty.model_dump.return_value = {}
        out = MagicMock()
        out.action = [empty]
        assert caption_from_actions(out) == ""

    def test_magic_mock_model_dump_called_with_exclude_none(self):
        m = MagicMock()
        m.model_dump.return_value = {"input": {"text": "hi"}}
        out = MagicMock()
        out.action = [m]
        assert caption_from_actions(out) == 'Typing "hi"'
        m.model_dump.assert_called_once_with(exclude_none=True)

    def test_all_action_types_via_structured_path(self):
        cases = [
            (_FakeAction("upload_file", {}), "Uploading a file"),
            (_FakeAction("go_back", {}), "Going back"),
            (_FakeAction("wait", {}), "Waiting for the page"),
            (_FakeAction("request_human_takeover", {}), "Handing this step to you"),
            (_FakeAction("solve_captcha_with_help", {}), "Handing this step to you"),
            (_FakeAction("done", {}), "Wrapping up"),
            (_FakeAction("extract", {}), "Reading the page"),
            (_FakeAction("read_file", {}), "Reading the page"),
            (_FakeAction("send_keys", {"text": "hi"}), 'Typing "hi"'),
            (_FakeAction("scroll_to_text", {}), "Scrolling"),
            (_FakeAction("select_dropdown", {}), "Choosing an option"),
        ]
        for action, want in cases:
            out = _FakeOutput([action])
            assert caption_from_actions(out) == want, f"mismatch for {want}"

    def test_mixed_structured_actions(self):
        out = _FakeOutput(
            [
                _FakeAction("navigate", {"url": "https://example.com"}),
                _FakeAction("input", {"text": "query"}),
                _FakeAction("click", {}),
            ]
        )
        assert caption_from_actions(out) == 'Opening example.com, Typing "query", Clicking'

    def test_handoff_and_done_mixed(self):
        out = _FakeOutput([_FakeAction("request_human_takeover", {}), _FakeAction("done", {})])
        assert caption_from_actions(out) == "Handing this step to you, Wrapping up"
