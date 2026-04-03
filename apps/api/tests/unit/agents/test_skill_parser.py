"""Unit tests for app.agents.skills.parser — SKILL.md parsing and generation."""

import pytest

from app.agents.skills.parser import (
    generate_skill_md,
    parse_skill_md,
    strip_frontmatter,
    validate_skill_content,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SKILL_MD = """---
name: my-skill
description: A useful skill for testing.
target: executor
---

# Instructions

Do the thing.
"""

VALID_SKILL_MD_MINIMAL = """---
name: my-skill
description: A useful skill.
---

Body here.
"""

SKILL_MD_WITH_ALLOWED_TOOLS = """---
name: tool-skill
description: Skill with allowed tools.
allowed-tools: Read Write Bash
---

Use the tools.
"""

SKILL_MD_WITH_ALLOWED_TOOLS_LIST = """---
name: tool-skill
description: Skill with allowed tools as a list.
allowed-tools:
  - Read
  - Write
  - Bash
---

Use the tools.
"""

SKILL_MD_WITH_SUBAGENT_ID = """---
name: gmail-skill
description: Gmail-specific skill.
subagent_id: gmail_agent
---

Handle emails.
"""

SKILL_MD_WITH_METADATA = """---
name: meta-skill
description: Skill with metadata.
metadata:
  author: test
  version: 1
---

Metadata body.
"""


# ---------------------------------------------------------------------------
# parse_skill_md
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    """Tests for parse_skill_md."""

    def test_parse_valid(self) -> None:
        metadata, body = parse_skill_md(VALID_SKILL_MD)
        assert metadata.name == "my-skill"
        assert metadata.description == "A useful skill for testing."
        assert metadata.target == "executor"
        assert "# Instructions" in body

    def test_parse_minimal(self) -> None:
        metadata, body = parse_skill_md(VALID_SKILL_MD_MINIMAL)
        assert metadata.name == "my-skill"
        assert metadata.target == "executor"  # default
        assert body == "Body here."

    def test_parse_allowed_tools_string(self) -> None:
        metadata, body = parse_skill_md(SKILL_MD_WITH_ALLOWED_TOOLS)
        assert metadata.allowed_tools == ["Read", "Write", "Bash"]

    def test_parse_allowed_tools_list(self) -> None:
        metadata, body = parse_skill_md(SKILL_MD_WITH_ALLOWED_TOOLS_LIST)
        assert metadata.allowed_tools == ["Read", "Write", "Bash"]

    def test_parse_subagent_id_maps_to_target(self) -> None:
        metadata, body = parse_skill_md(SKILL_MD_WITH_SUBAGENT_ID)
        assert metadata.target == "gmail_agent"

    def test_parse_metadata_converts_values_to_str(self) -> None:
        metadata, body = parse_skill_md(SKILL_MD_WITH_METADATA)
        assert metadata.metadata == {"author": "test", "version": "1"}

    def test_parse_empty_content_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_skill_md("")

    def test_parse_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_skill_md("   \n  ")

    def test_parse_no_frontmatter_raises(self) -> None:
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_md("# Just a heading\n\nNo frontmatter here.")

    def test_parse_invalid_yaml_raises(self) -> None:
        content = "---\n: invalid: yaml: {{{\n---\nBody"
        with pytest.raises(ValueError, match="Invalid YAML"):
            parse_skill_md(content)

    def test_parse_non_dict_frontmatter_raises(self) -> None:
        content = "---\n- just\n- a\n- list\n---\nBody"
        with pytest.raises(ValueError, match="mapping"):
            parse_skill_md(content)

    def test_parse_missing_name_raises(self) -> None:
        content = "---\ndescription: no name\n---\nBody"
        with pytest.raises(Exception):
            parse_skill_md(content)

    def test_parse_missing_description_raises(self) -> None:
        content = "---\nname: no-desc\n---\nBody"
        with pytest.raises(Exception):
            parse_skill_md(content)

    def test_parse_body_is_stripped(self) -> None:
        content = "---\nname: a\ndescription: b\n---\n\n  body text  \n\n"
        _, body = parse_skill_md(content)
        assert body == "body text"

    def test_parse_optional_license(self) -> None:
        content = "---\nname: a\ndescription: b\nlicense: MIT\n---\nBody"
        metadata, _ = parse_skill_md(content)
        assert metadata.license == "MIT"

    def test_parse_optional_compatibility(self) -> None:
        content = "---\nname: a\ndescription: b\ncompatibility: python3.11+\n---\nBody"
        metadata, _ = parse_skill_md(content)
        assert metadata.compatibility == "python3.11+"


# ---------------------------------------------------------------------------
# strip_frontmatter
# ---------------------------------------------------------------------------


class TestStripFrontmatter:
    """Tests for strip_frontmatter."""

    def test_strips_frontmatter(self) -> None:
        result = strip_frontmatter(VALID_SKILL_MD)
        assert "---" not in result
        assert "name:" not in result
        assert "# Instructions" in result

    def test_returns_content_without_frontmatter_unchanged(self) -> None:
        result = strip_frontmatter("# Just a heading\nSome text")
        assert result == "# Just a heading\nSome text"

    def test_empty_content_returns_empty(self) -> None:
        assert strip_frontmatter("") == ""

    def test_none_like_empty_returns_empty(self) -> None:
        # strip_frontmatter checks `if not content`
        assert strip_frontmatter("") == ""

    def test_body_is_stripped(self) -> None:
        content = "---\nname: a\n---\n\n  spaced body  \n\n"
        result = strip_frontmatter(content)
        assert result == "spaced body"


# ---------------------------------------------------------------------------
# validate_skill_content
# ---------------------------------------------------------------------------


class TestValidateSkillContent:
    """Tests for validate_skill_content."""

    def test_valid_content_no_errors(self) -> None:
        errors = validate_skill_content(VALID_SKILL_MD)
        assert errors == []

    def test_empty_content(self) -> None:
        errors = validate_skill_content("")
        assert any("empty" in e for e in errors)

    def test_whitespace_only(self) -> None:
        errors = validate_skill_content("   \n\t  ")
        assert any("empty" in e for e in errors)

    def test_missing_frontmatter(self) -> None:
        errors = validate_skill_content("No frontmatter here.")
        assert any("frontmatter" in e.lower() for e in errors)

    def test_invalid_yaml(self) -> None:
        errors = validate_skill_content("---\n: bad: {{{\n---\nBody")
        assert any("YAML" in e for e in errors)

    def test_non_dict_frontmatter(self) -> None:
        errors = validate_skill_content("---\n- list\n---\nBody")
        assert any("mapping" in e.lower() for e in errors)

    def test_missing_name(self) -> None:
        content = "---\ndescription: hello\n---\nBody"
        errors = validate_skill_content(content)
        assert any("name" in e for e in errors)

    def test_missing_description(self) -> None:
        content = "---\nname: valid-name\n---\nBody"
        errors = validate_skill_content(content)
        assert any("description" in e for e in errors)

    def test_name_too_long(self) -> None:
        content = f"---\nname: {'a' * 65}\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert any("too long" in e for e in errors)

    def test_name_invalid_format(self) -> None:
        content = "---\nname: Invalid_Name\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert any("lowercase" in e for e in errors)

    def test_name_consecutive_hyphens(self) -> None:
        content = "---\nname: bad--name\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert any("consecutive" in e for e in errors)

    def test_empty_description(self) -> None:
        content = "---\nname: valid\ndescription: ''\n---\nBody"
        errors = validate_skill_content(content)
        assert any("description" in e and "empty" in e for e in errors)

    def test_description_too_long(self) -> None:
        long_desc = "x" * 1025
        content = f"---\nname: valid\ndescription: {long_desc}\n---\nBody"
        errors = validate_skill_content(content)
        assert any("description too long" in e for e in errors)

    def test_compatibility_too_long(self) -> None:
        long_compat = "x" * 501
        content = f"---\nname: valid\ndescription: ok\ncompatibility: {long_compat}\n---\nBody"
        errors = validate_skill_content(content)
        assert any("compatibility" in e for e in errors)

    def test_body_too_many_lines_warning(self) -> None:
        long_body = "\n".join(["line"] * 501)
        content = f"---\nname: valid\ndescription: ok\n---\n{long_body}"
        errors = validate_skill_content(content)
        assert any("lines" in e for e in errors)

    def test_valid_with_all_optional_fields(self) -> None:
        content = """---
name: full-skill
description: A complete skill.
target: executor
license: MIT
compatibility: python3.11
metadata:
  author: test
---

Complete body.
"""
        errors = validate_skill_content(content)
        assert errors == []


# ---------------------------------------------------------------------------
# generate_skill_md
# ---------------------------------------------------------------------------


class TestGenerateSkillMd:
    """Tests for generate_skill_md."""

    def test_generates_valid_content(self) -> None:
        content = generate_skill_md(
            name="test-skill",
            description="A test skill.",
            instructions="Do something.",
        )
        assert "---" in content
        assert "test-skill" in content
        assert "Do something." in content

    def test_generated_content_round_trips(self) -> None:
        content = generate_skill_md(
            name="roundtrip",
            description="Round trip test.",
            instructions="Execute the plan.",
            target="executor",
        )
        metadata, body = parse_skill_md(content)
        assert metadata.name == "roundtrip"
        assert metadata.description == "Round trip test."
        assert metadata.target == "executor"
        assert "Execute the plan." in body

    def test_generates_with_metadata(self) -> None:
        content = generate_skill_md(
            name="meta-skill",
            description="With metadata.",
            instructions="Instructions here.",
            metadata={"author": "tester"},
        )
        assert "author" in content

    def test_generates_with_custom_target(self) -> None:
        content = generate_skill_md(
            name="target-skill",
            description="Custom target.",
            instructions="Body.",
            target="gmail_agent",
        )
        metadata, _ = parse_skill_md(content)
        assert metadata.target == "gmail_agent"

    def test_invalid_name_raises(self) -> None:
        with pytest.raises((ValueError, Exception)):
            generate_skill_md(
                name="Invalid Name!",
                description="Bad name.",
                instructions="Body.",
            )

    def test_empty_description_raises(self) -> None:
        with pytest.raises((ValueError, Exception)):
            generate_skill_md(
                name="valid-name",
                description="",
                instructions="Body.",
            )

    def test_no_metadata_omits_key(self) -> None:
        content = generate_skill_md(
            name="simple",
            description="Simple skill.",
            instructions="Do it.",
        )
        # metadata key should not appear if None/empty
        # (the function only adds metadata if truthy)
        metadata, _ = parse_skill_md(content)
        assert metadata.metadata == {} or "metadata" not in content.split("---")[1]

    def test_validates_generated_output(self) -> None:
        """generate_skill_md runs validate_skill_content and raises on errors."""
        # This indirectly tests the round-trip validation.
        content = generate_skill_md(
            name="validated",
            description="Validated skill.",
            instructions="Short instructions.",
        )
        errors = validate_skill_content(content)
        assert errors == []
