"""Unit tests for Notion <-> Markdown bidirectional conversion utilities."""

from typing import Any

import pytest

from app.utils.notion_md import (
    _add_tab_space,
    _apply_annotations,
    _bold,
    _bullet,
    _callout,
    _code_block,
    _divider,
    _equation,
    _heading1,
    _heading2,
    _heading3,
    _image,
    _inline_code,
    _inline_equation,
    _italic,
    _link,
    _quote,
    _strikethrough,
    _todo,
    _toggle,
    _underline,
    block_to_markdown,
    blocks_to_markdown,
    extract_plain_text,
    markdown_to_notion_blocks,
    rich_text_to_markdown,
    simplify_block,
)

# =============================================================================
# Helper Formatters
# =============================================================================


class TestBold:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("hello", "**hello**"),
            ("", "****"),
            ("two words", "**two words**"),
            ("**nested**", "****nested****"),
        ],
    )
    def test_bold(self, text: str, expected: str) -> None:
        assert _bold(text) == expected


class TestItalic:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("hello", "_hello_"),
            ("", "__"),
            ("two words", "_two words_"),
        ],
    )
    def test_italic(self, text: str, expected: str) -> None:
        assert _italic(text) == expected


class TestStrikethrough:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("hello", "~~hello~~"),
            ("", "~~~~"),
            ("two words", "~~two words~~"),
        ],
    )
    def test_strikethrough(self, text: str, expected: str) -> None:
        assert _strikethrough(text) == expected


class TestUnderline:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("hello", "<u>hello</u>"),
            ("", "<u></u>"),
            ("two words", "<u>two words</u>"),
        ],
    )
    def test_underline(self, text: str, expected: str) -> None:
        assert _underline(text) == expected


class TestInlineCode:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("hello", "`hello`"),
            ("", "``"),
            ("print('hi')", "`print('hi')`"),
        ],
    )
    def test_inline_code(self, text: str, expected: str) -> None:
        assert _inline_code(text) == expected


class TestInlineEquation:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("x^2", "$x^2$"),
            ("", "$$"),
            ("a + b = c", "$a + b = c$"),
        ],
    )
    def test_inline_equation(self, text: str, expected: str) -> None:
        assert _inline_equation(text) == expected


class TestLink:
    @pytest.mark.parametrize(
        "text, href, expected",
        [
            ("Google", "https://google.com", "[Google](https://google.com)"),
            ("", "https://example.com", "[](https://example.com)"),
            ("link", "", "[link]()"),
        ],
    )
    def test_link(self, text: str, href: str, expected: str) -> None:
        assert _link(text, href) == expected


class TestCodeBlock:
    @pytest.mark.parametrize(
        "text, language, expected",
        [
            ("print('hi')", "python", "```python\nprint('hi')\n```"),
            ("code here", None, "```\ncode here\n```"),
            ("some text", "plain text", "```text\nsome text\n```"),
            ("x = 1", "", "```\nx = 1\n```"),
            ("multi\nline\ncode", "js", "```js\nmulti\nline\ncode\n```"),
        ],
    )
    def test_code_block(self, text: str, language: str | None, expected: str) -> None:
        assert _code_block(text, language) == expected


class TestEquation:
    def test_equation_block(self) -> None:
        assert _equation("E = mc^2") == "$$\nE = mc^2\n$$"

    def test_empty_equation(self) -> None:
        assert _equation("") == "$$\n\n$$"


class TestHeadings:
    @pytest.mark.parametrize(
        "func, text, expected",
        [
            (_heading1, "Title", "# Title"),
            (_heading1, "", "# "),
            (_heading2, "Subtitle", "## Subtitle"),
            (_heading2, "", "## "),
            (_heading3, "Section", "### Section"),
            (_heading3, "", "### "),
        ],
    )
    def test_headings(self, func: Any, text: str, expected: str) -> None:
        assert func(text) == expected


class TestQuote:
    def test_single_line(self) -> None:
        assert _quote("hello") == "> hello"

    def test_multiline(self) -> None:
        assert _quote("line1\nline2\nline3") == "> line1\n> line2\n> line3"

    def test_empty(self) -> None:
        assert _quote("") == "> "


class TestBullet:
    @pytest.mark.parametrize(
        "text, count, expected",
        [
            ("item", None, "- item"),
            ("item", 1, "1. item"),
            ("item", 3, "3. item"),
            ("  spaced  ", None, "- spaced"),
            ("  spaced  ", 2, "2. spaced"),
            ("item", 0, "- item"),  # 0 is falsy, so acts like bulleted
        ],
    )
    def test_bullet(self, text: str, count: int | None, expected: str) -> None:
        assert _bullet(text, count) == expected


class TestTodo:
    @pytest.mark.parametrize(
        "text, checked, expected",
        [
            ("task", True, "- [x] task"),
            ("task", False, "- [ ] task"),
            ("", True, "- [x] "),
            ("", False, "- [ ] "),
        ],
    )
    def test_todo(self, text: str, checked: bool, expected: str) -> None:
        assert _todo(text, checked) == expected


class TestAddTabSpace:
    @pytest.mark.parametrize(
        "text, n, expected",
        [
            ("hello", 0, "hello"),
            ("hello", -1, "hello"),
            ("hello", 1, "\thello"),
            ("hello", 2, "\t\thello"),
            ("line1\nline2", 1, "\tline1\n\tline2"),
            ("line1\nline2\nline3", 2, "\t\tline1\n\t\tline2\n\t\tline3"),
            ("single", 3, "\t\t\tsingle"),
            ("a  b\nc", 1, "\ta  b\n\tc"),
        ],
    )
    def test_add_tab_space(self, text: str, n: int, expected: str) -> None:
        assert _add_tab_space(text, n) == expected

    def test_default_tab_count_is_zero(self) -> None:
        assert _add_tab_space("hello") == "hello"


class TestDivider:
    def test_divider(self) -> None:
        assert _divider() == "---"


class TestToggle:
    @pytest.mark.parametrize(
        "summary, children, expected",
        [
            (None, None, ""),
            (None, "content", "content"),
            ("Summary", None, "<details><summary>Summary</summary></details>"),
            (
                "Summary",
                "Children",
                "<details><summary>Summary</summary>Children</details>",
            ),
            ("", None, ""),  # empty string is falsy
            ("", "content", "content"),
        ],
    )
    def test_toggle(self, summary: str | None, children: str | None, expected: str) -> None:
        assert _toggle(summary, children) == expected


class TestCallout:
    def test_with_emoji_icon(self) -> None:
        icon = {"type": "emoji", "emoji": "💡"}
        result = _callout("Some text", icon)
        assert result == "> 💡 Some text"

    def test_without_icon(self) -> None:
        result = _callout("Some text", None)
        assert result == "> Some text"

    def test_with_non_emoji_icon(self) -> None:
        icon = {"type": "file", "file": {"url": "https://example.com/icon.png"}}
        result = _callout("Some text", icon)
        assert result == "> Some text"

    def test_with_empty_icon_dict(self) -> None:
        result = _callout("Some text", {})
        assert result == "> Some text"

    def test_with_heading_in_text(self) -> None:
        icon = {"type": "emoji", "emoji": "⚠️"}
        result = _callout("## Warning Title", icon)
        assert result == "> ## ⚠️ Warning Title"

    def test_with_heading_no_icon(self) -> None:
        result = _callout("# Title", None)
        assert result == "> # Title"

    def test_multiline_callout(self) -> None:
        icon = {"type": "emoji", "emoji": "📝"}
        result = _callout("Line 1\nLine 2", icon)
        assert result == "> 📝 Line 1\n> Line 2"

    def test_heading_with_no_emoji_in_icon(self) -> None:
        """Icon type is emoji but emoji key is missing."""
        icon = {"type": "emoji"}
        result = _callout("## Heading", icon)
        # emoji is "" so formatted_emoji is "", heading match fires
        assert result == "> ## Heading"

    def test_heading_embedded_in_text_not_matched(self) -> None:
        """Heading regex is anchored — '#' appearing mid-text is not a heading."""
        assert _callout("Text with # NotHeading", None) == "> Text with # NotHeading"

    def test_heading_requires_space_after_hashes(self) -> None:
        assert _callout("#Title", None) == "> #Title"

    def test_six_hash_heading_boundary_with_emoji(self) -> None:
        """Six hashes is the max heading level; emoji moves after the hashes."""
        icon = {"type": "emoji", "emoji": "💡"}
        assert _callout("###### Six", icon) == "> ###### 💡 Six"

    def test_seven_hash_heading_exceeds_max_level(self) -> None:
        """Seven hashes is not a heading — emoji stays at the start of the line."""
        icon = {"type": "emoji", "emoji": "💡"}
        assert _callout("####### Seven", icon) == "> 💡 ####### Seven"


class TestImage:
    def test_image(self) -> None:
        assert _image("alt text", "https://img.com/a.png") == "![alt text](https://img.com/a.png)"

    def test_empty_alt(self) -> None:
        assert _image("", "https://img.com/a.png") == "![](https://img.com/a.png)"


# =============================================================================
# Annotation Application
# =============================================================================


class TestApplyAnnotations:
    def test_code_annotation(self) -> None:
        result = _apply_annotations("hello", {"code": True})
        assert result == "`hello`"

    def test_bold_annotation(self) -> None:
        result = _apply_annotations("hello", {"bold": True})
        assert result == "**hello**"

    def test_italic_annotation(self) -> None:
        result = _apply_annotations("hello", {"italic": True})
        assert result == "_hello_"

    def test_strikethrough_annotation(self) -> None:
        result = _apply_annotations("hello", {"strikethrough": True})
        assert result == "~~hello~~"

    def test_underline_annotation(self) -> None:
        result = _apply_annotations("hello", {"underline": True})
        assert result == "<u>hello</u>"

    def test_multiple_annotations(self) -> None:
        result = _apply_annotations("hello", {"bold": True, "italic": True})
        assert result == "_**hello**_"

    def test_all_annotations(self) -> None:
        result = _apply_annotations(
            "hello",
            {
                "code": True,
                "bold": True,
                "italic": True,
                "strikethrough": True,
                "underline": True,
            },
        )
        assert result == "<u>~~_**`hello`**_~~</u>"

    def test_empty_text(self) -> None:
        result = _apply_annotations("", {"bold": True})
        assert result == ""

    def test_whitespace_only(self) -> None:
        result = _apply_annotations("   ", {"bold": True})
        assert result == "   "

    def test_preserves_leading_space(self) -> None:
        result = _apply_annotations("  hello", {"bold": True})
        assert result == "  **hello**"

    def test_preserves_trailing_space(self) -> None:
        result = _apply_annotations("hello  ", {"bold": True})
        assert result == "**hello**  "

    def test_preserves_both_spaces(self) -> None:
        result = _apply_annotations("  hello  ", {"bold": True})
        assert result == "  **hello**  "

    def test_no_annotations(self) -> None:
        result = _apply_annotations("hello", {})
        assert result == "hello"

    def test_false_annotations(self) -> None:
        result = _apply_annotations("hello", {"bold": False, "italic": False})
        assert result == "hello"


# =============================================================================
# Rich Text Conversion
# =============================================================================


class TestRichTextToMarkdown:
    def test_empty_list(self) -> None:
        assert rich_text_to_markdown([]) == ""

    def test_plain_text(self) -> None:
        rich_text = [{"type": "text", "plain_text": "Hello world", "annotations": {}}]
        assert rich_text_to_markdown(rich_text) == "Hello world"

    def test_equation_type(self) -> None:
        rich_text = [{"type": "equation", "equation": {"expression": "x^2 + y^2 = z^2"}}]
        assert rich_text_to_markdown(rich_text) == "$x^2 + y^2 = z^2$"

    def test_equation_missing_expression(self) -> None:
        rich_text = [{"type": "equation", "equation": {}}]
        assert rich_text_to_markdown(rich_text) == "$$"

    def test_equation_item_without_equation_key(self) -> None:
        """A missing equation payload defaults to an empty expression."""
        rich_text = [{"type": "equation"}]
        assert rich_text_to_markdown(rich_text) == "$$"

    def test_equation_item_skips_annotation_and_link_handling(self) -> None:
        """Equation items return immediately — plain_text/href are ignored."""
        rich_text = [
            {
                "type": "equation",
                "equation": {"expression": "x"},
                "plain_text": "ignored",
                "href": "https://example.com",
            },
            {"type": "text", "plain_text": "after", "annotations": {}},
        ]
        assert rich_text_to_markdown(rich_text) == "$x$after"

    def test_text_with_bold_annotation(self) -> None:
        rich_text = [
            {
                "type": "text",
                "plain_text": "bold text",
                "annotations": {"bold": True},
            }
        ]
        assert rich_text_to_markdown(rich_text) == "**bold text**"

    def test_text_with_href(self) -> None:
        rich_text = [
            {
                "type": "text",
                "plain_text": "Click here",
                "annotations": {},
                "href": "https://example.com",
            }
        ]
        assert rich_text_to_markdown(rich_text) == "[Click here](https://example.com)"

    def test_bold_text_with_href(self) -> None:
        rich_text = [
            {
                "type": "text",
                "plain_text": "Link",
                "annotations": {"bold": True},
                "href": "https://example.com",
            }
        ]
        assert rich_text_to_markdown(rich_text) == "[**Link**](https://example.com)"

    def test_multiple_rich_text_segments(self) -> None:
        rich_text = [
            {"type": "text", "plain_text": "Hello ", "annotations": {}},
            {
                "type": "text",
                "plain_text": "world",
                "annotations": {"bold": True},
            },
        ]
        assert rich_text_to_markdown(rich_text) == "Hello **world**"

    def test_mixed_equations_and_text(self) -> None:
        rich_text = [
            {"type": "text", "plain_text": "The formula is ", "annotations": {}},
            {"type": "equation", "equation": {"expression": "E=mc^2"}},
        ]
        assert rich_text_to_markdown(rich_text) == "The formula is $E=mc^2$"

    def test_missing_plain_text_key(self) -> None:
        """When plain_text key is missing, defaults to empty string."""
        rich_text = [{"type": "text", "annotations": {}}]
        assert rich_text_to_markdown(rich_text) == ""

    def test_missing_annotations_key(self) -> None:
        """When annotations key is missing, defaults to empty dict."""
        rich_text = [{"type": "text", "plain_text": "hello"}]
        assert rich_text_to_markdown(rich_text) == "hello"


# =============================================================================
# Block to Markdown Conversion
# =============================================================================


class TestBlockToMarkdown:
    def test_not_a_dict(self) -> None:
        assert block_to_markdown("not a dict") == ""  # type: ignore[arg-type]

    def test_missing_type(self) -> None:
        assert block_to_markdown({"data": "something"}) == ""

    def test_paragraph(self) -> None:
        block = {
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "plain_text": "Hello world", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "Hello world"

    def test_heading_1(self) -> None:
        block = {
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"type": "text", "plain_text": "Title", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "# Title"

    def test_heading_2(self) -> None:
        block = {
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "plain_text": "Subtitle", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "## Subtitle"

    def test_heading_3(self) -> None:
        block = {
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "plain_text": "Section", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "### Section"

    def test_code_block(self) -> None:
        block = {
            "type": "code",
            "code": {
                "language": "python",
                "rich_text": [
                    {
                        "type": "text",
                        "plain_text": "print('hi')",
                        "annotations": {},
                    }
                ],
            },
        }
        assert block_to_markdown(block) == "```python\nprint('hi')\n```"

    def test_code_block_plain_text_language_normalized(self) -> None:
        block = {
            "type": "code",
            "code": {
                "language": "plain text",
                "rich_text": [
                    {
                        "type": "text",
                        "plain_text": "some text",
                        "annotations": {},
                    }
                ],
            },
        }
        assert block_to_markdown(block) == "```text\nsome text\n```"

    def test_quote(self) -> None:
        block = {
            "type": "quote",
            "quote": {
                "rich_text": [
                    {
                        "type": "text",
                        "plain_text": "A wise saying",
                        "annotations": {},
                    }
                ]
            },
        }
        assert block_to_markdown(block) == "> A wise saying"

    def test_callout_with_icon(self) -> None:
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "plain_text": "Important", "annotations": {}}],
                "icon": {"type": "emoji", "emoji": "⚠️"},
            },
        }
        assert block_to_markdown(block) == "> ⚠️ Important"

    def test_callout_without_icon(self) -> None:
        block = {
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "plain_text": "Note", "annotations": {}}],
            },
        }
        assert block_to_markdown(block) == "> Note"

    def test_bulleted_list_item(self) -> None:
        block = {
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "plain_text": "Item 1", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "- Item 1"

    def test_numbered_list_item(self) -> None:
        block = {
            "type": "numbered_list_item",
            "numbered_list_item": {
                "number": 3,
                "rich_text": [{"type": "text", "plain_text": "Third item", "annotations": {}}],
            },
        }
        assert block_to_markdown(block) == "3. Third item"

    def test_numbered_list_item_no_number(self) -> None:
        block = {
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": [{"type": "text", "plain_text": "Item", "annotations": {}}],
            },
        }
        # number is None so _bullet returns bulleted style
        assert block_to_markdown(block) == "- Item"

    def test_to_do_checked(self) -> None:
        block = {
            "type": "to_do",
            "to_do": {
                "checked": True,
                "rich_text": [{"type": "text", "plain_text": "Done task", "annotations": {}}],
            },
        }
        assert block_to_markdown(block) == "- [x] Done task"

    def test_to_do_unchecked(self) -> None:
        block = {
            "type": "to_do",
            "to_do": {
                "checked": False,
                "rich_text": [{"type": "text", "plain_text": "Pending", "annotations": {}}],
            },
        }
        assert block_to_markdown(block) == "- [ ] Pending"

    def test_to_do_missing_checked_defaults_unchecked(self) -> None:
        block = {
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "plain_text": "Pending", "annotations": {}}],
            },
        }
        assert block_to_markdown(block) == "- [ ] Pending"

    def test_toggle(self) -> None:
        block = {
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "plain_text": "Toggle text", "annotations": {}}]
            },
        }
        result = block_to_markdown(block)
        assert result == "<details><summary>Toggle text</summary></details>"

    def test_image_external(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "![img.png](https://example.com/img.png)"

    def test_image_external_no_url(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "![image]()"

    def test_image_url_without_slash(self) -> None:
        """A URL with no '/' can't produce a filename — title stays 'image'."""
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "photo.jpg"},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "![image](photo.jpg)"

    def test_image_caption_item_missing_plain_text(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"type": "text"}],
            },
        }
        assert block_to_markdown(block) == "![img.png](https://example.com/img.png)"

    def test_image_caption_whitespace_only_falls_back_to_filename(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "   "}],
            },
        }
        assert block_to_markdown(block) == "![img.png](https://example.com/img.png)"

    def test_image_caption_preserves_non_whitespace(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "  My caption  "}],
            },
        }
        assert block_to_markdown(block) == "![My caption](https://example.com/img.png)"

    def test_image_block_without_image_data(self) -> None:
        block = {"type": "image"}
        assert block_to_markdown(block) == "![image]()"

    def test_image_data_without_caption_key(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
            },
        }
        assert block_to_markdown(block) == "![img.png](https://example.com/img.png)"

    def test_image_caption_multiple_items_concatenated(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "A"}, {"plain_text": "B"}],
            },
        }
        assert block_to_markdown(block) == "![AB](https://example.com/img.png)"

    def test_image_external_without_external_key(self) -> None:
        block = {"type": "image", "image": {"type": "external"}}
        assert block_to_markdown(block) == "![image]()"

    def test_image_file_without_file_key(self) -> None:
        block = {"type": "image", "image": {"type": "file"}}
        assert block_to_markdown(block) == "![image]()"

    def test_image_file_without_url(self) -> None:
        block = {"type": "image", "image": {"type": "file", "file": {}}}
        assert block_to_markdown(block) == "![image]()"

    def test_image_file(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "file",
                "file": {"url": "https://s3.amazonaws.com/photo.jpg"},
                "caption": [],
            },
        }
        result = block_to_markdown(block)
        assert result == "![photo.jpg](https://s3.amazonaws.com/photo.jpg)"

    def test_image_with_caption(self) -> None:
        block = {
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "My caption"}],
            },
        }
        assert block_to_markdown(block) == "![My caption](https://example.com/img.png)"

    def test_divider(self) -> None:
        block = {"type": "divider", "divider": {}}
        assert block_to_markdown(block) == "---"

    def test_equation_block(self) -> None:
        block = {
            "type": "equation",
            "equation": {"expression": "a^2 + b^2 = c^2"},
        }
        assert block_to_markdown(block) == "$$\na^2 + b^2 = c^2\n$$"

    def test_equation_block_missing_expression(self) -> None:
        block = {"type": "equation", "equation": {}}
        assert block_to_markdown(block) == "$$\n\n$$"

    def test_table_row(self) -> None:
        block = {
            "type": "table_row",
            "table_row": {
                "cells": [
                    [{"type": "text", "plain_text": "A", "annotations": {}}],
                    [{"type": "text", "plain_text": "B", "annotations": {}}],
                ]
            },
        }
        assert block_to_markdown(block) == "| A | B |"

    def test_table_row_empty_cells(self) -> None:
        block = {"type": "table_row", "table_row": {"cells": []}}
        assert block_to_markdown(block) == "|  |"

    def test_table_type_returns_placeholder(self) -> None:
        block = {"type": "table", "table": {}}
        assert block_to_markdown(block) == "[TABLE - see children for rows]"

    def test_video_external(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/watch?v=abc"},
                "caption": [],
            },
        }
        result = block_to_markdown(block)
        assert result == "[watch?v=abc](https://youtube.com/watch?v=abc)"

    def test_video_with_caption(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/v"},
                "caption": [{"plain_text": "My Video"}],
            },
        }
        assert block_to_markdown(block) == "[My Video](https://youtube.com/v)"

    def test_video_caption_whitespace_only_falls_back_to_filename(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/watch?v=abc"},
                "caption": [{"plain_text": "   "}],
            },
        }
        assert block_to_markdown(block) == "[watch?v=abc](https://youtube.com/watch?v=abc)"

    def test_video_caption_item_missing_plain_text(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/watch?v=abc"},
                "caption": [{"type": "text"}],
            },
        }
        assert block_to_markdown(block) == "[watch?v=abc](https://youtube.com/watch?v=abc)"

    def test_video_url_without_slash(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "video.mp4"},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "[video](video.mp4)"

    def test_video_external_no_url(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "[video]()"

    def test_video_data_without_caption_key(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/watch?v=abc"},
            },
        }
        assert block_to_markdown(block) == "[watch?v=abc](https://youtube.com/watch?v=abc)"

    def test_video_caption_multiple_items_concatenated(self) -> None:
        block = {
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/watch?v=abc"},
                "caption": [{"plain_text": "A"}, {"plain_text": "B"}],
            },
        }
        assert block_to_markdown(block) == "[AB](https://youtube.com/watch?v=abc)"

    def test_video_external_without_external_key(self) -> None:
        block = {"type": "video", "video": {"type": "external"}}
        assert block_to_markdown(block) == "[video]()"

    def test_video_file_without_file_key(self) -> None:
        block = {"type": "video", "video": {"type": "file"}}
        assert block_to_markdown(block) == "[video]()"

    def test_video_file_without_url(self) -> None:
        block = {"type": "video", "video": {"type": "file", "file": {}}}
        assert block_to_markdown(block) == "[video]()"

    def test_file_block_with_url(self) -> None:
        block = {
            "type": "file",
            "file": {
                "type": "external",
                "external": {"url": "https://example.com/doc.txt"},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "[doc.txt](https://example.com/doc.txt)"

    def test_file_block_empty_content(self) -> None:
        block = {"type": "file", "file": {}}
        assert block_to_markdown(block) == ""

    def test_pdf_block(self) -> None:
        block = {
            "type": "pdf",
            "pdf": {
                "type": "file",
                "file": {"url": "https://s3.example.com/doc.pdf"},
                "caption": [],
            },
        }
        assert block_to_markdown(block) == "[doc.pdf](https://s3.example.com/doc.pdf)"

    def test_bookmark(self) -> None:
        block = {
            "type": "bookmark",
            "bookmark": {"url": "https://example.com"},
        }
        assert block_to_markdown(block) == "[bookmark](https://example.com)"

    def test_bookmark_missing_url(self) -> None:
        block = {"type": "bookmark", "bookmark": {}}
        assert block_to_markdown(block) == "[bookmark]()"

    def test_embed(self) -> None:
        block = {
            "type": "embed",
            "embed": {"url": "https://twitter.com/status/123"},
        }
        assert block_to_markdown(block) == "[embed](https://twitter.com/status/123)"

    def test_link_preview(self) -> None:
        block = {
            "type": "link_preview",
            "link_preview": {"url": "https://example.com/preview"},
        }
        assert block_to_markdown(block) == "[link_preview](https://example.com/preview)"

    def test_link_to_page_page_id(self) -> None:
        block = {
            "type": "link_to_page",
            "link_to_page": {"type": "page_id", "page_id": "abc123"},
        }
        assert block_to_markdown(block) == "[link_to_page](https://www.notion.so/abc123)"

    def test_link_to_page_database_id(self) -> None:
        block = {
            "type": "link_to_page",
            "link_to_page": {"type": "database_id", "database_id": "db456"},
        }
        assert block_to_markdown(block) == "[link_to_page](https://www.notion.so/db456)"

    def test_link_to_page_unknown_type(self) -> None:
        block = {
            "type": "link_to_page",
            "link_to_page": {"type": "unknown"},
        }
        assert block_to_markdown(block) == "[link_to_page]()"

    def test_link_to_page_missing_page_id(self) -> None:
        block = {
            "type": "link_to_page",
            "link_to_page": {"type": "page_id"},
        }
        assert block_to_markdown(block) == "[link_to_page](https://www.notion.so/)"

    def test_link_to_page_missing_database_id(self) -> None:
        block = {
            "type": "link_to_page",
            "link_to_page": {"type": "database_id"},
        }
        assert block_to_markdown(block) == "[link_to_page](https://www.notion.so/)"

    def test_child_page(self) -> None:
        block = {
            "type": "child_page",
            "child_page": {"title": "My Page"},
        }
        assert block_to_markdown(block) == "## My Page"

    def test_child_page_no_title(self) -> None:
        block = {"type": "child_page", "child_page": {}}
        assert block_to_markdown(block) == "## "

    def test_child_database(self) -> None:
        block = {
            "type": "child_database",
            "child_database": {"title": "My Database"},
        }
        assert block_to_markdown(block) == "## My Database"

    def test_child_database_no_title(self) -> None:
        block = {
            "type": "child_database",
            "child_database": {},
        }
        assert block_to_markdown(block) == "## child_database"

    def test_unknown_block_type_with_rich_text(self) -> None:
        """Unknown types fall through to the default rich_text extraction."""
        block = {
            "type": "synced_block",
            "synced_block": {
                "rich_text": [{"type": "text", "plain_text": "synced", "annotations": {}}]
            },
        }
        assert block_to_markdown(block) == "synced"

    def test_unknown_block_type_no_rich_text(self) -> None:
        block = {"type": "column_list", "column_list": {}}
        assert block_to_markdown(block) == ""

    def test_block_type_without_data_key(self) -> None:
        """A type with no matching data key degrades to empty values."""
        assert block_to_markdown({"type": "paragraph"}) == ""
        assert block_to_markdown({"type": "code"}) == "```\n\n```"
        assert block_to_markdown({"type": "callout"}) == "> "
        assert block_to_markdown({"type": "numbered_list_item"}) == "- "
        assert block_to_markdown({"type": "to_do"}) == "- [ ] "
        assert block_to_markdown({"type": "child_page"}) == "## "
        assert block_to_markdown({"type": "child_database"}) == "## child_database"
        assert block_to_markdown({"type": "bookmark"}) == "[bookmark]()"
        assert block_to_markdown({"type": "link_to_page"}) == "[link_to_page]()"
        assert block_to_markdown({"type": "table_row"}) == "|  |"
        assert block_to_markdown({"type": "video"}) == ""
        assert block_to_markdown({"type": "file"}) == ""
        assert block_to_markdown({"type": "equation"}) == "$$\n\n$$"

    def test_text_key_fallback(self) -> None:
        """Some blocks use 'text' instead of 'rich_text'."""
        block = {
            "type": "custom",
            "custom": {"text": [{"plain_text": "T", "annotations": {}}]},
        }
        assert block_to_markdown(block) == "T"

    def test_code_block_without_language_key(self) -> None:
        block = {
            "type": "code",
            "code": {"rich_text": [{"type": "text", "plain_text": "x = 1", "annotations": {}}]},
        }
        assert block_to_markdown(block) == "```\nx = 1\n```"


# =============================================================================
# Block List to Markdown
# =============================================================================


class TestBlocksToMarkdown:
    def test_empty_blocks(self) -> None:
        assert blocks_to_markdown([]) == ""

    def test_single_paragraph(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Hello", "annotations": {}}]
                },
            }
        ]
        assert blocks_to_markdown(blocks) == "Hello"

    def test_numbered_list_index_tracking(self) -> None:
        blocks = [
            {
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "First", "annotations": {}}]
                },
            },
            {
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "Second", "annotations": {}}]
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Break", "annotations": {}}]
                },
            },
            {
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "Restart", "annotations": {}}]
                },
            },
        ]
        result = blocks_to_markdown(blocks)
        lines = result.split("\n")
        assert lines[0] == "1. First"
        assert lines[1] == "2. Second"
        assert lines[2] == "Break"
        assert lines[3] == "1. Restart"

    def test_skips_unsupported_blocks(self) -> None:
        blocks = [
            {"type": "unsupported"},
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Visible", "annotations": {}}]
                },
            },
        ]
        assert blocks_to_markdown(blocks) == "Visible"  # type: ignore[arg-type]

    def test_unsupported_block_children_skipped_too(self) -> None:
        """The continue skips the block AND its children."""
        blocks = [
            {
                "type": "unsupported",
                "children": [
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "plain_text": "Hidden", "annotations": {}}
                            ]
                        },
                    }
                ],
            }
        ]
        assert blocks_to_markdown(blocks) == ""

    def test_empty_block_content_followed_by_content(self) -> None:
        """Empty markdown is dropped without leaving a leading newline."""
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": []}},
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Hello", "annotations": {}}]
                },
            },
        ]
        assert blocks_to_markdown(blocks) == "Hello"

    def test_children_producing_empty_markdown_not_appended(self) -> None:
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "Parent", "annotations": {}}]
                },
                "children": [{"type": "paragraph", "paragraph": {"rich_text": []}}],
            }
        ]
        assert blocks_to_markdown(blocks) == "- Parent"

    def test_include_block_ids_false_ignores_ids(self) -> None:
        blocks = [
            {
                "id": "block-123",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Text", "annotations": {}}]
                },
            }
        ]
        assert blocks_to_markdown(blocks) == "Text"

    def test_nesting(self) -> None:
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "Parent", "annotations": {}}]
                },
                "children": [
                    {
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "plain_text": "Child",
                                    "annotations": {},
                                }
                            ]
                        },
                    }
                ],
            }
        ]
        result = blocks_to_markdown(blocks)
        lines = result.split("\n")
        assert lines[0] == "- Parent"
        assert lines[1] == "\t- Child"

    def test_include_block_ids(self) -> None:
        blocks = [
            {
                "id": "block-123",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Text", "annotations": {}}]
                },
            }
        ]
        result = blocks_to_markdown(blocks, include_block_ids=True)
        lines = result.split("\n")
        assert lines[0] == "<!-- block:block-123 -->"
        assert lines[1] == "Text"

    def test_include_block_ids_nested(self) -> None:
        blocks = [
            {
                "id": "parent-id",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "plain_text": "Parent", "annotations": {}}]
                },
                "children": [
                    {
                        "id": "child-id",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "plain_text": "Child",
                                    "annotations": {},
                                }
                            ]
                        },
                    }
                ],
            }
        ]
        result = blocks_to_markdown(blocks, include_block_ids=True)
        assert "<!-- block:parent-id -->" in result
        assert "\t<!-- block:child-id -->" in result

    def test_block_without_id_skips_comment(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "No ID", "annotations": {}}]
                },
            }
        ]
        result = blocks_to_markdown(blocks, include_block_ids=True)
        assert "<!-- block:" not in result
        assert result == "No ID"

    def test_empty_block_content_skipped(self) -> None:
        """Block that produces empty markdown is not added to result."""
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": []},
            }
        ]
        assert blocks_to_markdown(blocks) == ""

    def test_multiple_block_types(self) -> None:
        blocks = [
            {
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "plain_text": "Title", "annotations": {}}]
                },
            },
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "plain_text": "Body text", "annotations": {}}]
                },
            },
            {"type": "divider", "divider": {}},
        ]
        result = blocks_to_markdown(blocks)
        lines = result.split("\n")
        assert lines[0] == "# Title"
        assert lines[1] == "Body text"
        assert lines[2] == "---"


# =============================================================================
# Simplify Block
# =============================================================================


class TestSimplifyBlock:
    def test_paragraph(self) -> None:
        block = {
            "id": "abc",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"plain_text": "Hello world"}],
            },
        }
        result = simplify_block(block)
        assert result["id"] == "abc"
        assert result["type"] == "paragraph"
        assert result["text"] == "Hello world"

    def test_no_rich_text(self) -> None:
        block = {"id": "abc", "type": "divider", "divider": {}}
        result = simplify_block(block)
        assert "text" not in result

    def test_child_page(self) -> None:
        block = {
            "id": "p1",
            "type": "child_page",
            "child_page": {"title": "My Page"},
        }
        result = simplify_block(block)
        assert result["title"] == "My Page"

    def test_child_page_no_title(self) -> None:
        block = {"id": "p1", "type": "child_page", "child_page": {}}
        result = simplify_block(block)
        assert result["title"] == ""

    def test_child_database_no_title(self) -> None:
        block = {"id": "d1", "type": "child_database", "child_database": {}}
        result = simplify_block(block)
        assert result["title"] == ""

    def test_child_database(self) -> None:
        block = {
            "id": "d1",
            "type": "child_database",
            "child_database": {"title": "My DB"},
        }
        result = simplify_block(block)
        assert result["title"] == "My DB"

    def test_to_do(self) -> None:
        block = {
            "id": "t1",
            "type": "to_do",
            "to_do": {
                "checked": True,
                "rich_text": [{"plain_text": "Task"}],
            },
        }
        result = simplify_block(block)
        assert result["checked"] is True
        assert result["text"] == "Task"

    def test_to_do_missing_checked_defaults_false(self) -> None:
        block = {
            "id": "t1",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"plain_text": "Task"}],
            },
        }
        result = simplify_block(block)
        assert result["checked"] is False

    def test_code(self) -> None:
        block = {
            "id": "c1",
            "type": "code",
            "code": {
                "language": "python",
                "rich_text": [{"plain_text": "x = 1"}],
            },
        }
        result = simplify_block(block)
        assert result["language"] == "python"
        assert result["text"] == "x = 1"

    def test_image_external(self) -> None:
        block = {
            "id": "i1",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "My image"}],
            },
        }
        result = simplify_block(block)
        assert result["url"] == "https://example.com/img.png"
        assert result["caption"] == "My image"

    def test_image_file(self) -> None:
        block = {
            "id": "i2",
            "type": "image",
            "image": {
                "type": "file",
                "file": {"url": "https://s3.example.com/img.png"},
                "caption": [],
            },
        }
        result = simplify_block(block)
        assert result["url"] == "https://s3.example.com/img.png"
        assert result["caption"] == ""

    def test_image_missing_url_and_caption(self) -> None:
        block = {"id": "i3", "type": "image", "image": {}}
        result = simplify_block(block)
        assert result["url"] == ""
        assert result["caption"] == ""

    def test_image_caption_item_missing_plain_text(self) -> None:
        block = {
            "id": "i4",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"type": "text"}],
            },
        }
        result = simplify_block(block)
        assert result["caption"] == ""

    def test_video(self) -> None:
        block = {
            "id": "v1",
            "type": "video",
            "video": {
                "type": "external",
                "external": {"url": "https://youtube.com/v"},
                "caption": [],
            },
        }
        result = simplify_block(block)
        assert result["url"] == "https://youtube.com/v"

    def test_bookmark(self) -> None:
        block = {
            "id": "b1",
            "type": "bookmark",
            "bookmark": {"url": "https://example.com"},
        }
        result = simplify_block(block)
        assert result["url"] == "https://example.com"

    def test_bookmark_missing_url(self) -> None:
        block = {"id": "b1", "type": "bookmark", "bookmark": {}}
        result = simplify_block(block)
        assert result["url"] == ""

    def test_block_type_without_data_key(self) -> None:
        """A block with a type but no matching data key has no text."""
        block = {"id": "x", "type": "paragraph"}
        result = simplify_block(block)
        assert "text" not in result

    def test_missing_id_defaults_empty(self) -> None:
        block = {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hi"}]}}
        result = simplify_block(block)
        assert result["id"] == ""

    def test_rich_text_item_missing_plain_text(self) -> None:
        block = {
            "id": "t1",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text"}]},
        }
        result = simplify_block(block)
        assert result["text"] == ""

    def test_child_page_without_data_key(self) -> None:
        block = {"id": "p1", "type": "child_page"}
        result = simplify_block(block)
        assert result["title"] == ""

    def test_child_database_without_data_key(self) -> None:
        block = {"id": "d1", "type": "child_database"}
        result = simplify_block(block)
        assert result["title"] == ""

    def test_to_do_without_data_key(self) -> None:
        block = {"id": "t1", "type": "to_do"}
        result = simplify_block(block)
        assert result["checked"] is False

    def test_code_without_language_key(self) -> None:
        block = {
            "id": "c1",
            "type": "code",
            "code": {"rich_text": [{"plain_text": "x = 1"}]},
        }
        result = simplify_block(block)
        assert result["language"] == ""

    def test_code_without_data_key(self) -> None:
        block = {"id": "c1", "type": "code"}
        result = simplify_block(block)
        assert result["language"] == ""

    def test_file_block(self) -> None:
        block = {
            "id": "f1",
            "type": "file",
            "file": {
                "type": "external",
                "external": {"url": "https://example.com/doc.txt"},
                "caption": [{"plain_text": "Doc"}],
            },
        }
        result = simplify_block(block)
        assert result["url"] == "https://example.com/doc.txt"
        assert result["caption"] == "Doc"

    def test_pdf_block(self) -> None:
        block = {
            "id": "pdf1",
            "type": "pdf",
            "pdf": {
                "type": "file",
                "file": {"url": "https://s3.example.com/report.pdf"},
                "caption": [],
            },
        }
        result = simplify_block(block)
        assert result["url"] == "https://s3.example.com/report.pdf"

    def test_image_without_data_key(self) -> None:
        block = {"id": "i5", "type": "image"}
        result = simplify_block(block)
        assert result["url"] == ""
        assert result["caption"] == ""

    def test_external_image_without_url(self) -> None:
        block = {
            "id": "i6",
            "type": "image",
            "image": {"type": "external", "external": {}, "caption": []},
        }
        result = simplify_block(block)
        assert result["url"] == ""

    def test_external_image_without_external_key(self) -> None:
        block = {
            "id": "i7",
            "type": "image",
            "image": {"type": "external", "caption": []},
        }
        result = simplify_block(block)
        assert result["url"] == ""

    def test_caption_multiple_items_concatenated(self) -> None:
        block = {
            "id": "i8",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [{"plain_text": "A"}, {"plain_text": "B"}],
            },
        }
        result = simplify_block(block)
        assert result["caption"] == "AB"

    def test_link_preview(self) -> None:
        block = {
            "id": "lp1",
            "type": "link_preview",
            "link_preview": {"url": "https://example.com/preview"},
        }
        result = simplify_block(block)
        assert result["url"] == "https://example.com/preview"

    def test_bookmark_without_data_key(self) -> None:
        block = {"id": "b2", "type": "bookmark"}
        result = simplify_block(block)
        assert result["url"] == ""

    def test_embed(self) -> None:
        block = {
            "id": "e1",
            "type": "embed",
            "embed": {"url": "https://embed.example.com"},
        }
        result = simplify_block(block)
        assert result["url"] == "https://embed.example.com"

    def test_has_children_flag(self) -> None:
        block = {
            "id": "p1",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "text"}]},
            "has_children": True,
        }
        result = simplify_block(block)
        assert result["has_children"] is True

    def test_no_has_children_flag(self) -> None:
        block = {
            "id": "p1",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "text"}]},
        }
        result = simplify_block(block)
        assert "has_children" not in result

    def test_children_recursive(self) -> None:
        block = {
            "id": "parent",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
            "children": [
                {
                    "id": "child",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Child"}]},
                }
            ],
        }
        result = simplify_block(block)
        assert len(result["children"]) == 1
        assert result["children"][0]["text"] == "Child"

    def test_missing_type(self) -> None:
        block = {"id": "x"}
        result = simplify_block(block)
        assert result["type"] == ""

    def test_text_key_fallback(self) -> None:
        """Some blocks use 'text' instead of 'rich_text'."""
        block = {
            "id": "t1",
            "type": "custom",
            "custom": {"text": [{"plain_text": "via text key"}]},
        }
        result = simplify_block(block)
        assert result["text"] == "via text key"

    def test_multiple_rich_text_items_concatenated(self) -> None:
        block = {
            "id": "m1",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"plain_text": "Hello "},
                    {"plain_text": "World"},
                ]
            },
        }
        result = simplify_block(block)
        assert result["text"] == "Hello World"


# =============================================================================
# Extract Plain Text
# =============================================================================


class TestExtractPlainText:
    def test_empty(self) -> None:
        assert extract_plain_text([]) == ""

    def test_single_block(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Hello"}]},
            }
        ]
        assert extract_plain_text(blocks) == "Hello"

    def test_multiple_blocks(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Line 1"}]},
            },
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Line 2"}]},
            },
        ]
        assert extract_plain_text(blocks) == "Line 1\nLine 2"

    def test_nested_children(self) -> None:
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
                "children": [
                    {
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"plain_text": "Child"}]},
                    }
                ],
            }
        ]
        assert extract_plain_text(blocks) == "Parent\nChild"

    def test_blocks_without_text(self) -> None:
        blocks = [
            {"type": "divider", "divider": {}},
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "After divider"}]},
            },
        ]
        assert extract_plain_text(blocks) == "After divider"

    def test_block_type_without_data_key(self) -> None:
        blocks = [{"type": "paragraph"}]
        assert extract_plain_text(blocks) == ""

    def test_rich_text_item_missing_plain_text(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text"}]},
            }
        ]
        assert extract_plain_text(blocks) == ""

    def test_empty_text_then_content(self) -> None:
        """Blocks whose text is empty must not leave a leading newline."""
        blocks = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": ""}]}},
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Hi"}]},
            },
        ]
        assert extract_plain_text(blocks) == "Hi"

    def test_child_producing_no_text_not_appended(self) -> None:
        blocks = [
            {
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "Parent"}]},
                "children": [{"type": "divider", "divider": {}}],
            }
        ]
        assert extract_plain_text(blocks) == "Parent"

    def test_multiple_rich_text_items_concatenated(self) -> None:
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "a"}, {"plain_text": "b"}]},
            }
        ]
        assert extract_plain_text(blocks) == "ab"

    def test_text_key_fallback(self) -> None:
        blocks = [
            {
                "type": "custom",
                "custom": {"text": [{"plain_text": "From text key"}]},
            }
        ]
        assert extract_plain_text(blocks) == "From text key"


# =============================================================================
# Markdown to Notion Blocks
# =============================================================================


class TestMarkdownToNotionBlocks:
    def test_empty_string(self) -> None:
        assert markdown_to_notion_blocks("") == []

    def test_blank_lines_only(self) -> None:
        assert markdown_to_notion_blocks("\n\n\n") == []

    def test_paragraph(self) -> None:
        result = markdown_to_notion_blocks("Hello world")
        assert len(result) == 1
        assert result[0] == {"block_property": "paragraph", "content": "Hello world"}

    def test_heading_1(self) -> None:
        result = markdown_to_notion_blocks("# Title")
        assert result[0] == {"block_property": "heading_1", "content": "Title"}

    def test_heading_2(self) -> None:
        result = markdown_to_notion_blocks("## Subtitle")
        assert result[0] == {"block_property": "heading_2", "content": "Subtitle"}

    def test_heading_3(self) -> None:
        result = markdown_to_notion_blocks("### Section")
        assert result[0] == {"block_property": "heading_3", "content": "Section"}

    def test_heading_order_matters(self) -> None:
        """### must be checked before ## which must be checked before #."""
        result = markdown_to_notion_blocks("### H3\n## H2\n# H1")
        assert result[0]["block_property"] == "heading_3"
        assert result[1]["block_property"] == "heading_2"
        assert result[2]["block_property"] == "heading_1"

    def test_code_block_with_language(self) -> None:
        md = "```python\nprint('hi')\n```"
        result = markdown_to_notion_blocks(md)
        assert len(result) == 1
        assert result[0] == {
            "type": "code",
            "code": {
                "language": "python",
                "rich_text": [{"type": "text", "text": {"content": "print('hi')"}}],
            },
        }

    def test_code_block_without_language(self) -> None:
        md = "```\nsome code\n```"
        result = markdown_to_notion_blocks(md)
        assert result[0]["code"]["language"] == "plain text"

    def test_code_block_multiline(self) -> None:
        md = "```js\nline1\nline2\nline3\n```"
        result = markdown_to_notion_blocks(md)
        assert result[0]["code"]["rich_text"][0]["text"]["content"] == "line1\nline2\nline3"

    def test_quote(self) -> None:
        result = markdown_to_notion_blocks("> A quote")
        assert result[0] == {"block_property": "quote", "content": "A quote"}

    def test_todo_unchecked(self) -> None:
        result = markdown_to_notion_blocks("- [ ] My task")
        assert result[0] == {"block_property": "to_do", "content": "My task"}

    def test_todo_checked_lowercase(self) -> None:
        result = markdown_to_notion_blocks("- [x] Done task")
        assert result[0] == {"block_property": "to_do", "content": "Done task"}

    def test_todo_checked_uppercase(self) -> None:
        result = markdown_to_notion_blocks("- [X] Done task")
        assert result[0] == {"block_property": "to_do", "content": "Done task"}

    def test_bullet_dash(self) -> None:
        result = markdown_to_notion_blocks("- Item one")
        assert result[0] == {
            "block_property": "bulleted_list_item",
            "content": "Item one",
        }

    def test_bullet_asterisk(self) -> None:
        result = markdown_to_notion_blocks("* Item one")
        assert result[0] == {
            "block_property": "bulleted_list_item",
            "content": "Item one",
        }

    def test_numbered_list(self) -> None:
        result = markdown_to_notion_blocks("1. First\n2. Second")
        assert result[0] == {
            "block_property": "numbered_list_item",
            "content": "First",
        }
        assert result[1] == {
            "block_property": "numbered_list_item",
            "content": "Second",
        }

    def test_numbered_list_multi_digit(self) -> None:
        result = markdown_to_notion_blocks("10. Tenth item")
        assert result[0] == {
            "block_property": "numbered_list_item",
            "content": "Tenth item",
        }

    def test_numbered_list_without_content_is_paragraph(self) -> None:
        result = markdown_to_notion_blocks("1.")
        assert result[0] == {"block_property": "paragraph", "content": "1."}

    def test_todo_without_content_is_bullet(self) -> None:
        """- [ ] with nothing after it doesn't match the todo regex (.+)."""
        result = markdown_to_notion_blocks("- [ ]")
        assert result[0] == {
            "block_property": "bulleted_list_item",
            "content": "[ ]",
        }

    def test_heading_without_space_is_paragraph(self) -> None:
        result = markdown_to_notion_blocks("#Title")
        assert result[0] == {"block_property": "paragraph", "content": "#Title"}

    def test_heading_without_content(self) -> None:
        """Trailing-space-only headings get stripped, then don't match '### '."""
        result = markdown_to_notion_blocks("### ")
        assert result[0] == {"block_property": "paragraph", "content": "###"}

    def test_quote_without_content(self) -> None:
        """'>' alone is stripped and doesn't match the '> ' quote rule."""
        result = markdown_to_notion_blocks("> ")
        assert result[0] == {"block_property": "paragraph", "content": ">"}

    def test_heading_marker_without_space_is_paragraph(self) -> None:
        """The heading rules require a space after the hashes."""
        for md in ["###x", "##x", "#x"]:
            result = markdown_to_notion_blocks(md)
            assert result[0] == {"block_property": "paragraph", "content": md}

    @pytest.mark.parametrize(
        "divider_md",
        ["---", "***", "___"],
    )
    def test_divider(self, divider_md: str) -> None:
        result = markdown_to_notion_blocks(divider_md)
        assert len(result) == 1
        assert result[0]["block_property"] == "paragraph"
        assert result[0]["content"] == "───"

    def test_callout_github_alert_style_matched_as_quote(self) -> None:
        """The > prefix matches the quote rule first, so GitHub-style callouts
        are returned as quotes rather than callouts."""
        result = markdown_to_notion_blocks("> [!NOTE] Important info")
        assert result[0] == {
            "block_property": "quote",
            "content": "[!NOTE] Important info",
        }

    def test_table_simple(self) -> None:
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        result = markdown_to_notion_blocks(md)
        assert len(result) == 1
        assert result[0]["type"] == "table"
        assert result[0]["table_width"] == 2
        assert result[0]["has_column_header"] is True
        assert len(result[0]["rows"]) == 2  # header row + 1 data row

    def test_table_only_separators(self) -> None:
        """A table with only separator rows produces no blocks."""
        md = "| --- | --- |"
        result = markdown_to_notion_blocks(md)
        assert len(result) == 0

    def test_table_rows_padded_to_header_width(self) -> None:
        md = "| A | B | C |\n| --- | --- | --- |\n| 1 |"
        result = markdown_to_notion_blocks(md)
        table = result[0]
        data_row_cells = table["rows"][1]["cells"]
        assert len(data_row_cells) == 3
        # Third cell should be padded empty
        assert data_row_cells[2] == [{"type": "text", "text": {"content": ""}}]

    def test_table_rows_trimmed_to_header_width(self) -> None:
        md = "| A | B |\n| --- | --- |\n| 1 | 2 | 3 | 4 |"
        result = markdown_to_notion_blocks(md)
        table = result[0]
        data_row_cells = table["rows"][1]["cells"]
        assert len(data_row_cells) == 2

    def test_table_aligned_separator_rows(self) -> None:
        """Alignment-marked separators (:---:, :--:) are filtered like plain ones."""
        md = "| A | B |\n| :--- | :---: |\n| 1 | 2 |"
        result = markdown_to_notion_blocks(md)
        assert len(result) == 1
        table = result[0]
        assert table["table_width"] == 2
        assert len(table["rows"]) == 2

    def test_table_cell_whitespace_stripped(self) -> None:
        md = "|  A  |  B  |\n| --- | --- |\n|  1  |  2  |"
        result = markdown_to_notion_blocks(md)
        table = result[0]
        header_cells = table["rows"][0]["cells"]
        assert header_cells[0][0]["text"]["content"] == "A"
        data_cells = table["rows"][1]["cells"]
        assert data_cells[1][0]["text"]["content"] == "2"

    def test_table_line_not_ending_in_pipe_is_paragraph(self) -> None:
        """Both |...| boundaries are required for table detection."""
        result = markdown_to_notion_blocks("| not a table")
        assert result[0] == {
            "block_property": "paragraph",
            "content": "| not a table",
        }

    def test_mixed_content(self) -> None:
        md = "# Title\n\nSome text\n\n- bullet\n\n1. numbered"
        result = markdown_to_notion_blocks(md)
        assert result[0]["block_property"] == "heading_1"
        assert result[1]["block_property"] == "paragraph"
        assert result[2]["block_property"] == "bulleted_list_item"
        assert result[3]["block_property"] == "numbered_list_item"

    def test_skips_empty_lines(self) -> None:
        md = "\n\nHello\n\n\nWorld\n\n"
        result = markdown_to_notion_blocks(md)
        assert len(result) == 2
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "World"

    def test_indented_line_treated_as_paragraph(self) -> None:
        md = "    indented text"
        result = markdown_to_notion_blocks(md)
        assert result[0]["block_property"] == "paragraph"
        assert result[0]["content"] == "indented text"

    def test_code_block_no_closing_fence(self) -> None:
        """Code block with no closing ``` should consume remaining lines."""
        md = "```python\nline1\nline2"
        result = markdown_to_notion_blocks(md)
        assert result[0]["type"] == "code"
        assert result[0]["code"]["rich_text"][0]["text"]["content"] == "line1\nline2"

    def test_code_block_not_first_line(self) -> None:
        md = "para\n```py\nc\n```"
        result = markdown_to_notion_blocks(md)
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {
            "type": "code",
            "code": {
                "language": "py",
                "rich_text": [{"type": "text", "text": {"content": "c"}}],
            },
        }

    def test_code_block_followed_by_paragraph(self) -> None:
        md = "```py\nc\n```\npara"
        result = markdown_to_notion_blocks(md)
        assert result[0]["type"] == "code"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_heading_1_followed_by_paragraph(self) -> None:
        result = markdown_to_notion_blocks("# H1\npara")
        assert result[0]["block_property"] == "heading_1"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_heading_3_followed_by_paragraph(self) -> None:
        result = markdown_to_notion_blocks("### H3\npara")
        assert result[0]["block_property"] == "heading_3"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_quote_followed_by_paragraph(self) -> None:
        result = markdown_to_notion_blocks("> q\npara")
        assert result[0]["block_property"] == "quote"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_bullet_followed_by_paragraph(self) -> None:
        result = markdown_to_notion_blocks("- b\npara")
        assert result[0]["block_property"] == "bulleted_list_item"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_divider_not_first_line(self) -> None:
        result = markdown_to_notion_blocks("para\n---")
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {"block_property": "paragraph", "content": "───"}

    def test_divider_followed_by_paragraph(self) -> None:
        result = markdown_to_notion_blocks("---\npara")
        assert result[0] == {"block_property": "paragraph", "content": "───"}
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_heading_2_not_first_line(self) -> None:
        result = markdown_to_notion_blocks("para\n## H2")
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {"block_property": "heading_2", "content": "H2"}

    def test_heading_3_not_first_line(self) -> None:
        result = markdown_to_notion_blocks("para\n### H3")
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {"block_property": "heading_3", "content": "H3"}

    def test_quote_not_first_line(self) -> None:
        result = markdown_to_notion_blocks("para\n> q")
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {"block_property": "quote", "content": "q"}

    def test_todo_not_first_line(self) -> None:
        result = markdown_to_notion_blocks("para\n- [x] task")
        assert result[0] == {"block_property": "paragraph", "content": "para"}
        assert result[1] == {"block_property": "to_do", "content": "task"}

    def test_consecutive_paragraphs(self) -> None:
        result = markdown_to_notion_blocks("Hello\nWorld")
        assert result[0] == {"block_property": "paragraph", "content": "Hello"}
        assert result[1] == {"block_property": "paragraph", "content": "World"}

    def test_separators_only_table_followed_by_paragraph(self) -> None:
        md = "| --- | --- |\npara"
        result = markdown_to_notion_blocks(md)
        assert result == [{"block_property": "paragraph", "content": "para"}]

    def test_table_followed_by_paragraph(self) -> None:
        md = "| A |\n| --- |\n| 1 |\npara"
        result = markdown_to_notion_blocks(md)
        assert result[0]["type"] == "table"
        assert result[1] == {"block_property": "paragraph", "content": "para"}

    def test_table_three_data_rows_all_preserved(self) -> None:
        md = "| A |\n| --- |\n| 1 |\n| 2 |\n| 3 |"
        result = markdown_to_notion_blocks(md)
        table = result[0]
        assert len(table["rows"]) == 4
        assert table["rows"][3]["cells"][0][0]["text"]["content"] == "3"

    def test_todo_before_bullet(self) -> None:
        """Todo pattern (- [ ]) must be matched before plain bullet (- )."""
        md = "- [ ] Task\n- Plain bullet"
        result = markdown_to_notion_blocks(md)
        assert result[0]["block_property"] == "to_do"
        assert result[1]["block_property"] == "bulleted_list_item"

    def test_quote_before_callout(self) -> None:
        """Plain > quote is matched before > [! callout. Callout check is after quote."""
        md = "> Normal quote"
        result = markdown_to_notion_blocks(md)
        assert result[0]["block_property"] == "quote"

    def test_callout_branch_unreachable_due_to_quote_priority(self) -> None:
        """The > [! callout check on line 625 is unreachable because the > quote
        check on line 595 matches first. All > lines become quotes."""
        for md in ["> [!WARNING] Be careful", "> [!TIP] A tip"]:
            result = markdown_to_notion_blocks(md)
            assert result[0]["block_property"] == "quote"
