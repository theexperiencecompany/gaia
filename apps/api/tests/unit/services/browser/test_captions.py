"""Captions a user reads on a browser step: the action's real target, never a bare verb."""

import pytest

from app.services.browser.captions import describe_action


@pytest.mark.parametrize(
    ("url", "caption"),
    [
        ("https://www.amazon.com/dp/B0", "Opening amazon.com"),
        ("https://news.ycombinator.com/item?id=1", "Opening news.ycombinator.com"),
        (None, "Opening the page"),
        ("", "Opening the page"),
        # A relative or schemeless URL carries no host to name.
        ("/checkout", "Opening the page"),
    ],
)
def test_opening_a_page_names_its_host_or_falls_back_to_the_page(
    url: str | None, caption: str
) -> None:
    assert describe_action("navigate", {"url": url}) == caption


@pytest.mark.parametrize(
    ("text", "target", "caption"),
    [
        ("blue shoes", "Search", 'Typing "blue shoes" into "Search"'),
        ("blue shoes", None, 'Typing "blue shoes"'),
        (None, "Search", 'Typing into "Search"'),
        ("   ", "Search", 'Typing into "Search"'),
        (None, None, "Typing"),
    ],
)
def test_typing_names_what_is_typed_and_where_whichever_of_them_is_known(
    text: str | None, target: str | None, caption: str
) -> None:
    assert describe_action("input", {"text": text}, target) == caption


def test_typing_collapses_multiline_text_and_target_onto_one_line() -> None:
    caption = describe_action("input", {"text": "line one\n  line two"}, "Message\nbox")

    assert caption == 'Typing "line one line two" into "Message box"'


def test_an_action_with_a_fixed_verb_uses_its_caption() -> None:
    assert describe_action("scroll", {"down": True}) == "Scrolling"
    assert describe_action("extract", {}) == "Reading the page"


def test_an_action_with_no_caption_is_named_by_its_words() -> None:
    assert describe_action("switch_tab", {"tab_id": "a1"}) == "switch tab"
