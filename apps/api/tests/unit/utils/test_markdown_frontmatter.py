"""Unit tests for markdown utilities: frontmatter splitting, detection, conversion."""

import pytest

from app.utils.markdown_utils import (
    convert_markdown_to_plain_text,
    split_yaml_frontmatter,
)


@pytest.mark.unit
class TestSplitYamlFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\ntitle: Hello\nauthor: Test\n---\n# Body here\nParagraph."
        result = split_yaml_frontmatter(content)

        assert result is not None
        frontmatter, body = result
        assert frontmatter == "title: Hello\nauthor: Test"
        assert body == "# Body here\nParagraph."

    def test_empty_body(self):
        content = "---\nkey: value\n---\n"
        result = split_yaml_frontmatter(content)

        assert result is not None
        frontmatter, body = result
        assert frontmatter == "key: value"
        assert body == ""

    def test_no_frontmatter(self):
        content = "# Just a heading\nSome text."
        result = split_yaml_frontmatter(content)
        assert result is None

    def test_empty_string(self):
        assert split_yaml_frontmatter("") is None

    def test_whitespace_only_input(self):
        """A string of only whitespace has no frontmatter delimiter."""
        assert split_yaml_frontmatter("   ") is None

    def test_unclosed_frontmatter(self):
        content = "---\nkey: value\nno closing delimiter"
        result = split_yaml_frontmatter(content)
        assert result is None

    def test_only_delimiters(self):
        content = "---\n---\n"
        result = split_yaml_frontmatter(content)

        assert result is not None
        frontmatter, _ = result
        assert frontmatter == ""

    def test_frontmatter_with_multiline_body(self):
        content = "---\nname: test-skill\n---\nLine 1\nLine 2\nLine 3"
        result = split_yaml_frontmatter(content)

        assert result is not None
        frontmatter, body = result
        assert frontmatter == "name: test-skill"
        assert body == "Line 1\nLine 2\nLine 3"

    def test_content_not_starting_with_delimiter(self):
        content = "some text\n---\nkey: value\n---\nbody"
        result = split_yaml_frontmatter(content)
        assert result is None

    def test_windows_line_endings(self):
        content = "---\r\ntitle: Hello\r\n---\r\nBody text"
        result = split_yaml_frontmatter(content)

        assert result is not None
        frontmatter, body = result
        # splitlines(keepends=True) preserves line endings; rstrip("\r\n") strips the trailing one
        assert frontmatter == "title: Hello"
        assert body == "Body text"


@pytest.mark.unit
class TestConvertMarkdownToPlainText:
    def test_strips_headers(self):
        result = convert_markdown_to_plain_text("## My Header")
        assert result == "My Header"

    def test_strips_bold(self):
        result = convert_markdown_to_plain_text("This is **bold** text")
        assert result == "This is bold text"

    def test_strips_italic(self):
        result = convert_markdown_to_plain_text("This is *italic* text")
        assert result == "This is italic text"

    def test_converts_links(self):
        result = convert_markdown_to_plain_text("[Click here](http://example.com)")  # NOSONAR
        assert result == "Click here"

    def test_strips_code_blocks(self):
        result = convert_markdown_to_plain_text("```\ncode here\n```\nAfter")
        assert "code here" not in result
        assert "After" in result

    def test_strips_inline_code(self):
        result = convert_markdown_to_plain_text("Use `code` here")
        assert result == "Use code here"

    def test_strips_blockquotes(self):
        result = convert_markdown_to_plain_text("> Quoted text")
        assert result == "Quoted text"

    def test_strips_list_markers(self):
        result = convert_markdown_to_plain_text("- item one\n- item two")
        assert "item one" in result
        assert "item two" in result
        assert "- " not in result

    def test_strips_ordered_list_markers(self):
        result = convert_markdown_to_plain_text("1. first\n2. second")
        assert "first" in result
        assert "second" in result

    def test_preserves_plain_text(self):
        text = "Hello world, this is a test."
        assert convert_markdown_to_plain_text(text) == text
