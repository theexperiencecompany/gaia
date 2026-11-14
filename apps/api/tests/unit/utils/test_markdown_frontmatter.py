"""Unit tests for markdown utilities: frontmatter splitting, detection, conversion."""

from app.utils.markdown_utils import json_blocks, split_yaml_frontmatter


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


class TestJsonBlocks:
    def test_each_fenced_block_is_a_candidate_trimmed(self):
        reply = 'Here:\n```json\n {"a": 1} \n```\nand\n```\n{"b": 2}\n```'

        assert json_blocks(reply) == ['{"a": 1}', '{"b": 2}']

    def test_an_empty_fenced_block_is_no_candidate(self):
        assert json_blocks('```json\n  \n```\n```\n{"b": 2}\n```') == ['{"b": 2}']

    def test_a_reply_with_no_fence_is_its_own_candidate(self):
        assert json_blocks('  {"a": 1}\n') == ['{"a": 1}']

    def test_a_blank_reply_has_no_candidate(self):
        assert json_blocks("  \n") == []
