"""Behaviour spec for app.agents.skills.parser — SKILL.md parse/validate/generate.

UNIT: app/agents/skills/parser.py :: parse_skill_md
EXPECTED: Turn raw SKILL.md text into (SkillMetadata, body). Empty/whitespace,
          missing-frontmatter, invalid-YAML and non-mapping inputs raise ValueError;
          missing required fields raise pydantic ValidationError. `allowed-tools`
          (hyphen key) maps to `allowed_tools`: a string is whitespace-split, a list
          passes through. `subagent_id` maps to `target`. `metadata` values are
          coerced to str. Body is whitespace-stripped.
MECHANISM: split_yaml_frontmatter -> yaml.safe_load -> key remapping -> SkillMetadata(**fm).
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - empty/whitespace content raises ValueError("...empty")          [guard branch]
  - no frontmatter raises ValueError("...frontmatter...")           [split None branch]
  - invalid YAML raises ValueError("Invalid YAML frontmatter...")   [except branch]
  - non-dict frontmatter raises ValueError("...mapping...")         [isinstance branch]
  - missing name / missing description raise ValidationError        [pydantic contract]
  - allowed-tools string is split on whitespace into a list         [str branch]
  - allowed-tools list passes through unchanged                     [list branch]
  - subagent_id is renamed to target (and subagent_id is removed)   [GAIA extension]
  - metadata values become str ("1" not 1)                          [dict-comp coercion]
  - returned body is the stripped markdown, default target=executor [return shape]

UNIT: app/agents/skills/parser.py :: strip_frontmatter
EXPECTED: Return body-only markdown. Empty -> "". No frontmatter -> the original
          content stripped. With frontmatter -> the body after the closing ---, stripped.
MECHANISM: if not content: ""; split_yaml_frontmatter; fall back to content.strip().
MUST-CATCH:
  - empty content returns "" (not None, not the input)              [guard branch]
  - content without frontmatter returns content.strip()            [split None branch]
  - frontmatter is removed and body is stripped                    [happy path]

UNIT: app/agents/skills/parser.py :: validate_skill_content
EXPECTED: Return a list of error strings (empty == valid). Reports empty content,
          missing frontmatter, invalid YAML, non-mapping frontmatter, missing
          name/description, name length>64, bad name format, consecutive hyphens,
          empty/oversized description, oversized compatibility, and an over-long
          body warning. Guard branches short-circuit (return early).
MECHANISM: split -> yaml.safe_load -> field checks; len()/regex boundary tests.
MUST-CATCH (boundaries pin const_int & compare mutants):
  - empty / whitespace returns exactly ["SKILL.md content is empty"] [early return]
  - missing frontmatter returns the frontmatter message only         [early return]
  - invalid YAML returns the "Invalid YAML" message only             [early return]
  - non-mapping returns the "mapping" message only                   [early return]
  - missing name AND missing description both reported               [two ifs]
  - name length 64 passes, 65 emits "name too long (65 chars, max 64)"[> 64 boundary]
  - name with uppercase/underscore emits the lowercase-format error  [regex str]
  - consecutive hyphens emits the "consecutive" error                [substring branch]
  - empty description emits "description must not be empty"           [strip branch]
  - description length 1024 passes, 1025 emits the too-long message  [> 1024 boundary]
  - compatibility length 500 passes, 501 emits the too-long message  [> 500 boundary]
  - body 500 lines passes, 501 emits "Body has 501 lines..."         [count+1 / > 500]

UNIT: app/agents/skills/parser.py :: generate_skill_md
EXPECTED: Build a SKILL.md string from components, validating name/description via
          SkillMetadata up front and round-trip-validating the output. metadata is
          included only when truthy. target defaults to "executor".
MECHANISM: SkillMetadata(...) -> build frontmatter dict -> yaml.dump -> f-string
           -> validate_skill_content (raise ValueError on any error).
MUST-CATCH:
  - output starts with "---\n", parses back to the given name/desc/target [structure]
  - custom target round-trips; default target is "executor"             [target wiring]
  - metadata present -> key+value appear and round-trip                  [if metadata]
  - metadata absent -> no "metadata:" line, parsed metadata == {}        [omission]
  - invalid name raises (SkillMetadata validation, before build)         [up-front guard]
  - empty description raises                                             [up-front guard]
  - the body (instructions) appears in the parsed-back body             [f-string body]

EQUIVALENT MUTANTS (allowed survivors, justified) — kill rate 94/99 = 0.95:
  - parse_skill_md / strip_frontmatter / validate_skill_content / generate_skill_md
    docstring `const_str -> ''` (4 mutants): a function docstring has no runtime
    effect, so emptying it is behaviour-preserving.
  - `'; '.join(errors)` separator `'; ' -> ''` in generate_skill_md's post-generation
    guard: name & description are validated up-front via SkillMetadata, so the
    round-trip validate_skill_content(generated_content) can only ever surface the
    single body-line-count error. With a one-element list, `'; '.join([x])` ==
    `''.join([x])` == x, so the separator is never exercised — equivalent.
"""

from pydantic import ValidationError
import pytest

from app.agents.skills.parser import (
    generate_skill_md,
    parse_skill_md,
    strip_frontmatter,
    validate_skill_content,
)

VALID_SKILL_MD = """---
name: my-skill
description: A useful skill for testing.
target: executor
---

# Instructions

Do the thing.
"""


# ---------------------------------------------------------------------------
# parse_skill_md
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    def test_parses_all_fields_and_strips_body(self) -> None:
        metadata, body = parse_skill_md(VALID_SKILL_MD)
        assert metadata.name == "my-skill"
        assert metadata.description == "A useful skill for testing."
        assert metadata.target == "executor"
        # body is the markdown after the closing ---, leading/trailing ws stripped
        assert body == "# Instructions\n\nDo the thing."

    def test_default_target_is_executor(self) -> None:
        content = "---\nname: my-skill\ndescription: A useful skill.\n---\n\nBody here.\n"
        metadata, body = parse_skill_md(content)
        assert metadata.target == "executor"
        assert metadata.allowed_tools == []
        assert metadata.metadata == {}
        assert body == "Body here."

    def test_allowed_tools_string_is_whitespace_split(self) -> None:
        content = (
            "---\nname: tool-skill\ndescription: Tools.\nallowed-tools: Read Write Bash\n---\nBody"
        )
        metadata, _ = parse_skill_md(content)
        assert metadata.allowed_tools == ["Read", "Write", "Bash"]

    def test_allowed_tools_list_passes_through(self) -> None:
        content = (
            "---\nname: tool-skill\ndescription: Tools.\n"
            "allowed-tools:\n  - Read\n  - Write\n  - Bash\n---\nBody"
        )
        metadata, _ = parse_skill_md(content)
        assert metadata.allowed_tools == ["Read", "Write", "Bash"]

    def test_subagent_id_is_renamed_to_target(self) -> None:
        content = "---\nname: gmail-skill\ndescription: Gmail.\nsubagent_id: gmail_agent\n---\nBody"
        metadata, _ = parse_skill_md(content)
        assert metadata.target == "gmail_agent"
        # subagent_id is consumed (popped), it is not a SkillMetadata field
        assert not hasattr(metadata, "subagent_id")

    def test_metadata_values_coerced_to_str(self) -> None:
        content = (
            "---\nname: meta-skill\ndescription: Meta.\n"
            "metadata:\n  author: test\n  version: 1\n---\nBody"
        )
        metadata, _ = parse_skill_md(content)
        # int 1 must be coerced to the string "1", not left as int
        assert metadata.metadata == {"author": "test", "version": "1"}
        assert metadata.metadata["version"] == "1"

    def test_empty_content_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="SKILL.md content is empty"):
            parse_skill_md("")

    def test_whitespace_only_content_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="SKILL.md content is empty"):
            parse_skill_md("   \n  ")

    def test_missing_frontmatter_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must start with YAML frontmatter"):
            parse_skill_md("# Just a heading\n\nNo frontmatter here.")

    def test_invalid_yaml_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid YAML frontmatter"):
            parse_skill_md("---\n: invalid: yaml: {{{\n---\nBody")

    def test_non_dict_frontmatter_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            parse_skill_md("---\n- just\n- a\n- list\n---\nBody")

    def test_missing_name_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_skill_md("---\ndescription: no name\n---\nBody")

    def test_missing_description_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            parse_skill_md("---\nname: no-desc\n---\nBody")


# ---------------------------------------------------------------------------
# strip_frontmatter
# ---------------------------------------------------------------------------


class TestStripFrontmatter:
    def test_strips_frontmatter_keeping_stripped_body(self) -> None:
        result = strip_frontmatter("---\nname: a\n---\n\n  body text  \n\n")
        assert result == "body text"

    def test_content_without_frontmatter_is_returned_stripped(self) -> None:
        result = strip_frontmatter("  # Just a heading\nSome text  \n")
        assert result == "# Just a heading\nSome text"

    def test_empty_content_returns_empty_string(self) -> None:
        result = strip_frontmatter("")
        assert result == ""


# ---------------------------------------------------------------------------
# validate_skill_content
# ---------------------------------------------------------------------------


class TestValidateSkillContent:
    def test_valid_content_returns_no_errors(self) -> None:
        assert validate_skill_content(VALID_SKILL_MD) == []

    def test_empty_content_returns_only_empty_error(self) -> None:
        assert validate_skill_content("") == ["SKILL.md content is empty"]

    def test_whitespace_only_returns_only_empty_error(self) -> None:
        assert validate_skill_content("   \n\t  ") == ["SKILL.md content is empty"]

    def test_missing_frontmatter_returns_only_frontmatter_error(self) -> None:
        assert validate_skill_content("No frontmatter here.") == [
            "Missing YAML frontmatter (must start with --- delimiters)"
        ]

    def test_invalid_yaml_returns_only_yaml_error(self) -> None:
        errors = validate_skill_content("---\n: bad: {{{\n---\nBody")
        assert len(errors) == 1
        assert errors[0].startswith("Invalid YAML:")

    def test_non_mapping_frontmatter_returns_only_mapping_error(self) -> None:
        assert validate_skill_content("---\n- list\n---\nBody") == [
            "Frontmatter must be a YAML mapping"
        ]

    def test_missing_name_and_description_both_reported(self) -> None:
        errors = validate_skill_content("---\nfoo: bar\n---\nBody")
        assert "Missing required field: name" in errors
        assert "Missing required field: description" in errors

    def test_name_length_64_is_accepted(self) -> None:
        content = f"---\nname: {'a' * 64}\ndescription: ok\n---\nBody"
        assert validate_skill_content(content) == []

    def test_name_length_65_reports_exact_too_long_message(self) -> None:
        content = f"---\nname: {'a' * 65}\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert "name too long (65 chars, max 64)" in errors

    def test_name_invalid_format_reports_lowercase_message(self) -> None:
        content = "---\nname: Invalid_Name\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert "name must be lowercase alphanumeric with hyphens only" in errors

    def test_name_consecutive_hyphens_reported(self) -> None:
        content = "---\nname: bad--name\ndescription: ok\n---\nBody"
        errors = validate_skill_content(content)
        assert "name must not contain consecutive hyphens" in errors

    def test_empty_description_reports_must_not_be_empty(self) -> None:
        content = "---\nname: valid\ndescription: ''\n---\nBody"
        errors = validate_skill_content(content)
        assert "description must not be empty" in errors

    def test_description_length_1024_is_accepted(self) -> None:
        content = f"---\nname: valid\ndescription: {'x' * 1024}\n---\nBody"
        assert validate_skill_content(content) == []

    def test_description_length_1025_reports_exact_too_long_message(self) -> None:
        content = f"---\nname: valid\ndescription: {'x' * 1025}\n---\nBody"
        errors = validate_skill_content(content)
        assert "description too long (1025 chars, max 1024)" in errors

    def test_compatibility_length_500_is_accepted(self) -> None:
        content = f"---\nname: valid\ndescription: ok\ncompatibility: {'x' * 500}\n---\nBody"
        assert validate_skill_content(content) == []

    def test_compatibility_length_501_reports_too_long(self) -> None:
        content = f"---\nname: valid\ndescription: ok\ncompatibility: {'x' * 501}\n---\nBody"
        errors = validate_skill_content(content)
        assert "compatibility too long (max 500 chars)" in errors

    def test_body_500_lines_is_accepted(self) -> None:
        body = "\n".join(["line"] * 500)
        content = f"---\nname: valid\ndescription: ok\n---\n{body}"
        assert validate_skill_content(content) == []

    def test_body_501_lines_reports_exact_line_count(self) -> None:
        body = "\n".join(["line"] * 501)
        content = f"---\nname: valid\ndescription: ok\n---\n{body}"
        errors = validate_skill_content(content)
        assert any(e.startswith("Body has 501 lines (recommended max 500).") for e in errors)


# ---------------------------------------------------------------------------
# generate_skill_md
# ---------------------------------------------------------------------------


class TestGenerateSkillMd:
    def test_output_structure_and_round_trip(self) -> None:
        content = generate_skill_md(
            name="roundtrip",
            description="Round trip test.",
            instructions="Execute the plan.",
            target="executor",
        )
        assert content.startswith("---\n")
        assert content.endswith("\n")
        # Block-style YAML (not flow {a: b}) — each field is its own line.
        assert "\nname: roundtrip\n" in content
        # Insertion order is preserved (sort_keys=False): name before description.
        assert content.index("name:") < content.index("description:")
        metadata, body = parse_skill_md(content)
        assert metadata.name == "roundtrip"
        assert metadata.description == "Round trip test."
        assert metadata.target == "executor"
        assert body == "Execute the plan."

    def test_default_target_is_executor(self) -> None:
        content = generate_skill_md(
            name="no-target",
            description="No explicit target.",
            instructions="Body.",
        )
        metadata, _ = parse_skill_md(content)
        assert metadata.target == "executor"

    def test_unicode_description_is_preserved_raw(self) -> None:
        content = generate_skill_md(
            name="uni",
            description="café ☕ skill",
            instructions="Body.",
        )
        # allow_unicode=True keeps real characters, not \\xE9 escapes.
        assert "café ☕ skill" in content
        metadata, _ = parse_skill_md(content)
        assert metadata.description == "café ☕ skill"

    def test_custom_target_round_trips(self) -> None:
        content = generate_skill_md(
            name="target-skill",
            description="Custom target.",
            instructions="Body.",
            target="gmail_agent",
        )
        metadata, _ = parse_skill_md(content)
        assert metadata.target == "gmail_agent"

    def test_metadata_included_and_round_trips(self) -> None:
        content = generate_skill_md(
            name="meta-skill",
            description="With metadata.",
            instructions="Instructions here.",
            metadata={"author": "tester"},
        )
        assert "metadata:" in content
        metadata, _ = parse_skill_md(content)
        assert metadata.metadata == {"author": "tester"}

    def test_no_metadata_omits_metadata_key(self) -> None:
        content = generate_skill_md(
            name="simple",
            description="Simple skill.",
            instructions="Do it.",
        )
        assert "metadata:" not in content
        metadata, _ = parse_skill_md(content)
        assert metadata.metadata == {}

    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            generate_skill_md(
                name="Invalid Name!",
                description="Bad name.",
                instructions="Body.",
            )

    def test_empty_description_raises(self) -> None:
        with pytest.raises(ValidationError):
            generate_skill_md(
                name="valid-name",
                description="",
                instructions="Body.",
            )

    def test_generated_content_failing_validation_raises_with_message(self) -> None:
        # Name/description pass up-front; the >500-line body fails the round-trip
        # validation, hitting the post-generation guard's exact error message.
        oversized_body = "\n".join(["line"] * 501)
        with pytest.raises(ValueError, match="Generated SKILL.md is invalid: Body has 501 lines"):
            generate_skill_md(
                name="valid-name",
                description="Valid description.",
                instructions=oversized_body,
            )
