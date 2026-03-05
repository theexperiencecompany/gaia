from app.utils.markdown_utils import split_yaml_frontmatter


class TestSplitYamlFrontmatter:
    def test_splits_basic_frontmatter(self):
        content = "---\nname: test\n---\n\nBody\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter == "name: test"
        assert body == "\nBody\n"

    def test_splits_with_crlf(self):
        content = "---\r\nname: test\r\n---\r\nBody\r\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter == "name: test"
        assert body == "Body\r\n"

    def test_accepts_delimiters_with_spaces(self):
        content = "---   \nname: test\n---\t\nBody\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter == "name: test"
        assert body == "Body\n"

    def test_empty_frontmatter_allowed(self):
        content = "---\n---\nBody\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter == ""
        assert body == "Body\n"

    def test_requires_frontmatter_at_start(self):
        content = "\n---\nname: test\n---\nBody\n"
        assert split_yaml_frontmatter(content) is None

    def test_missing_closing_delimiter_returns_none(self):
        content = "---\nname: test\nBody\n"
        assert split_yaml_frontmatter(content) is None

    def test_stops_at_first_closing_delimiter(self):
        content = "---\nname: test\n---\nBody\n---\nNot frontmatter\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter == "name: test"
        assert body == "Body\n---\nNot frontmatter\n"

    def test_large_input_does_not_crash(self):
        # Regression guard for performance/pathological inputs: should complete.
        big_yaml = "k: v\n" * 200_000
        content = f"---\n{big_yaml}---\nBody\n"
        split = split_yaml_frontmatter(content)
        assert split is not None
        frontmatter, body = split
        assert frontmatter.startswith("k: v")
        assert body == "Body\n"
