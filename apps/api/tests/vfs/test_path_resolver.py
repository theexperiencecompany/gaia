"""
Tests for VFS Path Resolver - Pure function tests with no external dependencies.

These tests verify path normalization, validation, and path building functions.
"""

import pytest

from app.services.vfs.path_resolver import (
    EXECUTOR_AGENT,
    RESERVED_NAMES,
    build_path,
    get_agent_root,
    get_extension,
    get_filename,
    get_files_path,
    get_notes_path,
    get_parent_path,
    get_session_path,
    get_skills_path,
    get_tool_output_path,
    get_user_root,
    join_path,
    normalize_path,
    parse_path,
    validate_user_access,
)


class TestNormalizePath:
    """Tests for normalize_path function."""

    def test_adds_leading_slash(self):
        assert normalize_path("users/123") == "/users/123"

    def test_removes_trailing_slash(self):
        assert normalize_path("/users/123/") == "/users/123"

    def test_preserves_root_slash(self):
        assert normalize_path("/") == "/"

    def test_removes_double_slashes(self):
        assert normalize_path("/users//123///global") == "/users/123/global"

    def test_converts_backslashes(self):
        assert normalize_path("\\users\\123\\global") == "/users/123/global"

    def test_removes_path_traversal(self):
        assert normalize_path("/users/../123") == "/users/123"
        assert normalize_path("/users/123/../global") == "/users/123/global"

    def test_handles_empty_string(self):
        assert normalize_path("") == "/"

    def test_complex_normalization(self):
        path = "users\\\\123//global/../files\\"
        result = normalize_path(path)
        assert result == "/users/123/global/files"


class TestValidateUserAccess:
    """Tests for validate_user_access function."""

    def test_valid_user_path(self):
        assert validate_user_access("/users/user123/global/files", "user123") is True

    def test_invalid_user_path(self):
        assert validate_user_access("/users/user456/global/files", "user123") is False

    def test_root_user_path(self):
        assert validate_user_access("/users/user123", "user123") is True

    def test_handles_unnormalized_path(self):
        assert validate_user_access("users/user123/global", "user123") is True

    def test_partial_match_fails(self):
        # user12 should not match user123
        assert validate_user_access("/users/user12/global", "user123") is False


class TestGetUserRoot:
    """Tests for get_user_root function."""

    def test_returns_global_path(self):
        assert get_user_root("user123") == "/users/user123/global"

    def test_with_different_user_ids(self):
        assert get_user_root("abc") == "/users/abc/global"
        assert get_user_root("123-456") == "/users/123-456/global"


class TestGetSkillsPath:
    """Tests for get_skills_path function."""

    def test_learned_skills(self):
        assert (
            get_skills_path("user123", "learned")
            == "/users/user123/global/skills/learned"
        )

    def test_custom_skills(self):
        assert (
            get_skills_path("user123", "custom")
            == "/users/user123/global/skills/custom"
        )

    def test_invalid_skill_type_raises(self):
        with pytest.raises(ValueError, match="Invalid skill_type"):
            get_skills_path("user123", "invalid")


class TestGetSessionPath:
    """Tests for get_session_path function."""

    def test_session_path(self):
        result = get_session_path("user123", "conv-abc-123")
        assert result == "/users/user123/global/executor/sessions/conv-abc-123"

    def test_with_complex_conversation_id(self):
        result = get_session_path("u1", "thread_2024-01-01_xyz")
        assert result == "/users/u1/global/executor/sessions/thread_2024-01-01_xyz"


class TestGetToolOutputPath:
    """Tests for get_tool_output_path function."""

    def test_basic_tool_output_path(self):
        result = get_tool_output_path(
            user_id="user123",
            conversation_id="conv1",
            agent_name="gmail",
            tool_call_id="tc_001",
            tool_name="send_email",
        )
        expected = (
            "/users/user123/global/executor/sessions/conv1/gmail/tc_001_send_email.json"
        )
        assert result == expected

    def test_executor_agent_tool_output(self):
        result = get_tool_output_path(
            user_id="user123",
            conversation_id="conv1",
            agent_name="executor",
            tool_call_id="tc_002",
            tool_name="web_search",
        )
        expected = "/users/user123/global/executor/sessions/conv1/executor/tc_002_web_search.json"
        assert result == expected

    def test_sanitizes_special_characters(self):
        result = get_tool_output_path(
            user_id="user123",
            conversation_id="conv1",
            agent_name="agent:test",
            tool_call_id="tc<003>",
            tool_name="tool|name",
        )
        # Special chars should be replaced with underscores
        assert ":" not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result


class TestGetNotesPath:
    """Tests for get_notes_path function."""

    def test_executor_notes(self):
        result = get_notes_path("user123", "executor")
        assert result == "/users/user123/global/executor/notes"

    def test_subagent_notes(self):
        result = get_notes_path("user123", "gmail")
        assert result == "/users/user123/global/subagents/gmail/notes"

    def test_different_subagents(self):
        assert (
            get_notes_path("u1", "github") == "/users/u1/global/subagents/github/notes"
        )
        assert get_notes_path("u1", "slack") == "/users/u1/global/subagents/slack/notes"


class TestGetFilesPath:
    """Tests for get_files_path function."""

    def test_executor_files(self):
        result = get_files_path("user123", "executor")
        assert result == "/users/user123/global/executor/files"

    def test_subagent_files(self):
        result = get_files_path("user123", "gmail")
        assert result == "/users/user123/global/subagents/gmail/files"


class TestGetAgentRoot:
    """Tests for get_agent_root function."""

    def test_executor_root(self):
        assert get_agent_root("user123", "executor") == "/users/user123/global/executor"

    def test_subagent_root(self):
        assert (
            get_agent_root("user123", "gmail")
            == "/users/user123/global/subagents/gmail"
        )


class TestParsePath:
    """Tests for parse_path function."""

    def test_parse_executor_session_path(self):
        path = "/users/user123/global/executor/sessions/conv1/gmail/file.json"
        result = parse_path(path)

        assert result["user_id"] == "user123"
        assert result["is_global"] is True
        assert result["agent_name"] == "executor"
        assert result["folder_type"] == "sessions"
        assert result["conversation_id"] == "conv1"

    def test_parse_subagent_notes_path(self):
        path = "/users/user123/global/subagents/gmail/notes/meeting.txt"
        result = parse_path(path)

        assert result["user_id"] == "user123"
        assert result["is_global"] is True
        assert result["agent_name"] == "gmail"
        assert result["folder_type"] == "notes"

    def test_parse_skills_path(self):
        path = "/users/user123/global/skills/learned/skill1.json"
        result = parse_path(path)

        assert result["user_id"] == "user123"
        assert result["is_global"] is True
        assert result["folder_type"] == "skills"

    def test_parse_minimal_path(self):
        path = "/users/user123"
        result = parse_path(path)

        assert result["user_id"] == "user123"
        assert result["is_global"] is False

    def test_parse_invalid_path(self):
        path = "/invalid/path"
        result = parse_path(path)

        assert result["user_id"] is None


class TestBuildPath:
    """Tests for build_path function."""

    def test_build_user_root(self):
        result = build_path("user123")
        assert result == "/users/user123/global"

    def test_build_agent_path(self):
        result = build_path("user123", agent_name="gmail")
        assert result == "/users/user123/global/subagents/gmail"

    def test_build_notes_path(self):
        result = build_path("user123", agent_name="executor", folder_type="notes")
        assert result == "/users/user123/global/executor/notes"

    def test_build_session_path(self):
        result = build_path(
            "user123",
            agent_name="executor",
            folder_type="sessions",
            conversation_id="conv1",
        )
        assert result == "/users/user123/global/executor/sessions/conv1"

    def test_build_with_filename(self):
        result = build_path(
            "user123",
            agent_name="executor",
            folder_type="notes",
            filename="meeting.txt",
        )
        assert result == "/users/user123/global/executor/notes/meeting.txt"

    def test_build_skills_path(self):
        result = build_path("user123", folder_type="skills")
        assert result == "/users/user123/global/skills"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_parent_path(self):
        assert (
            get_parent_path("/users/123/global/files/doc.txt")
            == "/users/123/global/files"
        )
        assert get_parent_path("/users/123") == "/users"
        assert get_parent_path("/users") == "/"

    def test_join_path(self):
        assert join_path("/users/123", "global", "files") == "/users/123/global/files"
        assert join_path("users", "123") == "/users/123"

    def test_get_filename(self):
        assert get_filename("/users/123/global/files/doc.txt") == "doc.txt"
        assert get_filename("/users/123/global/files/") == "files"

    def test_get_extension(self):
        assert get_extension("/path/to/file.json") == "json"
        assert get_extension("/path/to/file.TXT") == "txt"  # Lowercase
        assert get_extension("/path/to/file") == ""
        assert get_extension("/path/to/.hidden") == "hidden"


class TestConstants:
    """Tests for module constants."""

    def test_executor_agent_constant(self):
        assert EXECUTOR_AGENT == "executor"

    def test_reserved_names(self):
        assert "skills" in RESERVED_NAMES
        assert "executor" in RESERVED_NAMES
        assert "subagents" in RESERVED_NAMES
        assert "global" in RESERVED_NAMES
        assert "users" in RESERVED_NAMES
