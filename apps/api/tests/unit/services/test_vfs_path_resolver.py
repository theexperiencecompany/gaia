"""Tests for app.services.vfs.path_resolver."""

from app.services.vfs.path_resolver import (
    EXECUTOR_AGENT,
    RESERVED_NAMES,
    _sanitize_name,
    build_path,
    get_agent_root,
    get_custom_skill_path,
    get_extension,
    get_filename,
    get_files_path,
    get_notes_path,
    get_parent_path,
    get_session_path,
    get_skills_path,
    get_system_skill_path,
    get_system_skills_path,
    get_tool_output_path,
    get_user_root,
    join_path,
    normalize_path,
    parse_path,
    validate_user_access,
)


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


class TestNormalizePath:
    def test_simple_path(self) -> None:
        assert normalize_path("/users/123") == "/users/123"

    def test_backslash_conversion(self) -> None:
        assert normalize_path("\\users\\123") == "/users/123"

    def test_double_slashes(self) -> None:
        assert normalize_path("/users//123") == "/users/123"

    def test_ensures_leading_slash(self) -> None:
        assert normalize_path("users/123") == "/users/123"

    def test_removes_trailing_slash(self) -> None:
        assert normalize_path("/users/123/") == "/users/123"

    def test_root_stays_root(self) -> None:
        assert normalize_path("/") == "/"

    def test_resolves_parent_traversal(self) -> None:
        assert normalize_path("/users/123/global/../other") == "/users/123/other"

    def test_resolves_dot(self) -> None:
        assert normalize_path("/users/./123") == "/users/123"

    def test_double_dot_at_root(self) -> None:
        # Going above root should just stay at root
        assert normalize_path("/..") == "/"

    def test_empty_string(self) -> None:
        assert normalize_path("") == "/"


# ---------------------------------------------------------------------------
# validate_user_access
# ---------------------------------------------------------------------------


class TestValidateUserAccess:
    def test_own_path(self) -> None:
        assert validate_user_access("/users/u1/global/files", "u1") is True

    def test_own_root(self) -> None:
        assert validate_user_access("/users/u1", "u1") is True

    def test_other_user(self) -> None:
        assert validate_user_access("/users/u2/global/files", "u1") is False

    def test_system_path_allowed(self) -> None:
        assert validate_user_access("/system/skills/agent/skill", "u1") is True

    def test_random_path_denied(self) -> None:
        assert validate_user_access("/random/path", "u1") is False


# ---------------------------------------------------------------------------
# Simple path getters
# ---------------------------------------------------------------------------


class TestSimplePathGetters:
    def test_get_user_root(self) -> None:
        assert get_user_root("u1") == "/users/u1/global"

    def test_get_skills_path(self) -> None:
        assert get_skills_path("u1") == "/users/u1/skills"

    def test_get_system_skills_path(self) -> None:
        assert get_system_skills_path() == "/system/skills"

    def test_get_system_skill_path(self) -> None:
        result = get_system_skill_path("github_agent", "create-pr")
        assert result == "/system/skills/github_agent/create-pr"

    def test_get_custom_skill_path(self) -> None:
        result = get_custom_skill_path("u1", "executor", "my-skill")
        assert result == "/users/u1/skills/executor/my-skill"

    def test_get_session_path(self) -> None:
        result = get_session_path("u1", "conv123")
        assert result == "/users/u1/global/executor/sessions/conv123"


# ---------------------------------------------------------------------------
# get_tool_output_path
# ---------------------------------------------------------------------------


class TestGetToolOutputPath:
    def test_basic(self) -> None:
        result = get_tool_output_path("u1", "conv1", "executor", "tc1", "search")
        assert (
            result
            == "/users/u1/global/executor/sessions/conv1/executor/tc1_search.json"
        )

    def test_sanitizes_names(self) -> None:
        result = get_tool_output_path("u1", "conv1", "agent/bad", "tc:1", "tool*name")
        assert "//" not in result
        assert "*" not in result


# ---------------------------------------------------------------------------
# get_notes_path / get_files_path
# ---------------------------------------------------------------------------


class TestNotesAndFilesPaths:
    def test_executor_notes(self) -> None:
        assert get_notes_path("u1", "executor") == "/users/u1/global/executor/notes"

    def test_subagent_notes(self) -> None:
        assert (
            get_notes_path("u1", "gmail_agent")
            == "/users/u1/global/subagents/gmail_agent/notes"
        )

    def test_executor_files(self) -> None:
        assert get_files_path("u1", "executor") == "/users/u1/global/executor/files"

    def test_subagent_files(self) -> None:
        assert (
            get_files_path("u1", "github") == "/users/u1/global/subagents/github/files"
        )


# ---------------------------------------------------------------------------
# get_agent_root
# ---------------------------------------------------------------------------


class TestGetAgentRoot:
    def test_executor(self) -> None:
        assert get_agent_root("u1", "executor") == "/users/u1/global/executor"

    def test_subagent(self) -> None:
        assert get_agent_root("u1", "gmail") == "/users/u1/global/subagents/gmail"


# ---------------------------------------------------------------------------
# parse_path
# ---------------------------------------------------------------------------


class TestParsePath:
    def test_non_user_path(self) -> None:
        result = parse_path("/system/skills")
        assert result["user_id"] is None

    def test_user_root(self) -> None:
        result = parse_path("/users/u1")
        assert result["user_id"] == "u1"
        assert result["is_global"] is False

    def test_skills_path(self) -> None:
        result = parse_path("/users/u1/skills/agent/my-skill")
        assert result["user_id"] == "u1"
        assert result["folder_type"] == "skills"
        assert result["remaining"] == ["agent", "my-skill"]

    def test_executor_sessions(self) -> None:
        result = parse_path("/users/u1/global/executor/sessions/conv1/data")
        assert result["is_global"] is True
        assert result["agent_name"] == "executor"
        assert result["folder_type"] == "sessions"
        assert result["conversation_id"] == "conv1"
        assert result["remaining"] == ["data"]

    def test_executor_notes(self) -> None:
        result = parse_path("/users/u1/global/executor/notes/file.txt")
        assert result["agent_name"] == "executor"
        assert result["folder_type"] == "notes"

    def test_executor_files(self) -> None:
        result = parse_path("/users/u1/global/executor/files")
        assert result["folder_type"] == "files"

    def test_subagent_notes(self) -> None:
        result = parse_path("/users/u1/global/subagents/gmail/notes/draft.md")
        assert result["agent_name"] == "gmail"
        assert result["folder_type"] == "notes"

    def test_subagent_files(self) -> None:
        result = parse_path("/users/u1/global/subagents/gmail/files")
        assert result["agent_name"] == "gmail"
        assert result["folder_type"] == "files"

    def test_subagent_other_path(self) -> None:
        result = parse_path("/users/u1/global/subagents/gmail/custom")
        assert result["agent_name"] == "gmail"
        assert result["folder_type"] is None

    def test_global_unknown_level3(self) -> None:
        result = parse_path("/users/u1/global/unknown")
        assert result["is_global"] is True
        assert result["agent_name"] is None
        assert result["remaining"] == ["unknown"]

    def test_global_only(self) -> None:
        result = parse_path("/users/u1/global")
        assert result["is_global"] is True
        assert result["agent_name"] is None

    def test_non_global_extra(self) -> None:
        result = parse_path("/users/u1/other/stuff")
        assert result["user_id"] == "u1"
        assert result["is_global"] is False
        assert result["remaining"] == ["other", "stuff"]

    def test_executor_unknown_level4(self) -> None:
        result = parse_path("/users/u1/global/executor/unknown_folder")
        assert result["agent_name"] == "executor"
        assert result["folder_type"] is None
        assert "unknown_folder" in result["remaining"]

    def test_subagents_no_agent_name(self) -> None:
        result = parse_path("/users/u1/global/subagents")
        assert result["agent_name"] is None

    def test_executor_sessions_no_conv_id(self) -> None:
        result = parse_path("/users/u1/global/executor/sessions")
        assert result["folder_type"] == "sessions"
        assert result["conversation_id"] is None


# ---------------------------------------------------------------------------
# build_path
# ---------------------------------------------------------------------------


class TestBuildPath:
    def test_user_root_only(self) -> None:
        assert build_path("u1") == "/users/u1/global"

    def test_with_agent(self) -> None:
        assert build_path("u1", agent_name="executor") == "/users/u1/global/executor"

    def test_with_folder_type(self) -> None:
        result = build_path("u1", agent_name="executor", folder_type="notes")
        assert result == "/users/u1/global/executor/notes"

    def test_sessions_with_conversation(self) -> None:
        result = build_path(
            "u1", agent_name="executor", folder_type="sessions", conversation_id="c1"
        )
        assert result == "/users/u1/global/executor/sessions/c1"

    def test_skills_folder(self) -> None:
        result = build_path("u1", folder_type="skills")
        assert result == "/users/u1/skills"

    def test_with_filename(self) -> None:
        result = build_path(
            "u1", agent_name="executor", folder_type="files", filename="data.json"
        )
        assert result == "/users/u1/global/executor/files/data.json"

    def test_subagent(self) -> None:
        result = build_path("u1", agent_name="gmail")
        assert result == "/users/u1/global/subagents/gmail"


# ---------------------------------------------------------------------------
# _sanitize_name
# ---------------------------------------------------------------------------


class TestSanitizeName:
    def test_empty_name(self) -> None:
        assert _sanitize_name("") == "unknown"

    def test_normal_name(self) -> None:
        assert _sanitize_name("my_tool") == "my_tool"

    def test_removes_slashes(self) -> None:
        assert "/" not in _sanitize_name("a/b/c")

    def test_removes_special_chars(self) -> None:
        result = _sanitize_name('file:name*bad?"<>|')
        assert ":" not in result
        assert "*" not in result

    def test_strips_dots_and_spaces(self) -> None:
        result = _sanitize_name("...name...")
        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_collapses_underscores(self) -> None:
        result = _sanitize_name("a___b")
        assert result == "a_b"

    def test_all_bad_chars_returns_unknown(self) -> None:
        result = _sanitize_name("...")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_get_parent_path(self) -> None:
        assert get_parent_path("/users/u1/global/executor") == "/users/u1/global"

    def test_get_parent_path_root(self) -> None:
        assert get_parent_path("/foo") == "/"

    def test_join_path(self) -> None:
        assert join_path("/users", "u1", "global") == "/users/u1/global"

    def test_join_path_strips_slashes(self) -> None:
        assert join_path("/users/", "/u1/", "/global/") == "/users/u1/global"

    def test_get_filename(self) -> None:
        assert get_filename("/users/u1/file.txt") == "file.txt"

    def test_get_filename_no_slash(self) -> None:
        assert get_filename("/file.txt") == "file.txt"

    def test_get_extension(self) -> None:
        assert get_extension("/foo/bar.JSON") == "json"

    def test_get_extension_no_ext(self) -> None:
        assert get_extension("/foo/bar") == ""

    def test_get_extension_multiple_dots(self) -> None:
        assert get_extension("/foo/bar.tar.gz") == "gz"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_executor_agent(self) -> None:
        assert EXECUTOR_AGENT == "executor"

    def test_reserved_names_contains_expected(self) -> None:
        assert "skills" in RESERVED_NAMES
        assert "executor" in RESERVED_NAMES
        assert "subagents" in RESERVED_NAMES
