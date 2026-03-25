"""Unit tests for app.utils.mcp_utils module.

Tests cover:
- generate_pkce_pair: PKCE code_verifier/code_challenge generation
- wrap_tool_with_null_filter: null filtering, auth re-raise, connection error callback,
  user-friendly error messages
- wrap_tools_with_null_filter: batch wrapping
- extract_type_from_field: JSON Schema → Python type extraction, enums, anyOf, type lists
- serialize_args_schema: schema serialization, edge cases
"""

import base64
import hashlib
from typing import Any, Optional, Union
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.utils.mcp_utils import (
    _CONNECTION_ERROR_PATTERNS,
    extract_type_from_field,
    generate_pkce_pair,
    serialize_args_schema,
    wrap_tool_with_null_filter,
    wrap_tools_with_null_filter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str = "test_tool", arun: Optional[AsyncMock] = None) -> BaseTool:
    """Create a minimal BaseTool mock that behaves like a real LangChain tool."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool._arun = arun or AsyncMock(return_value="ok")
    return tool


# ---------------------------------------------------------------------------
# generate_pkce_pair
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGeneratePkcePair:
    """Tests for generate_pkce_pair — returns (code_verifier, code_challenge)."""

    def test_returns_tuple_of_two_strings(self) -> None:
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_challenge_is_s256_of_verifier(self) -> None:
        verifier, challenge = generate_pkce_pair()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        assert challenge == expected

    def test_successive_calls_produce_different_pairs(self) -> None:
        pair_a = generate_pkce_pair()
        pair_b = generate_pkce_pair()
        assert pair_a[0] != pair_b[0]
        assert pair_a[1] != pair_b[1]

    def test_verifier_is_url_safe(self) -> None:
        verifier, _ = generate_pkce_pair()
        # url-safe base64 uses only [A-Za-z0-9_-]
        assert all(c.isalnum() or c in ("_", "-") for c in verifier)


# ---------------------------------------------------------------------------
# wrap_tool_with_null_filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWrapToolWithNullFilter:
    """Tests for wrap_tool_with_null_filter — filters None kwargs before calling _arun."""

    async def test_filters_none_values(self) -> None:
        original = AsyncMock(return_value="result")
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        result = await wrapped._arun(a=1, b=None, c="hello", d=None)

        assert result == "result"
        original.assert_awaited_once_with(a=1, c="hello")

    async def test_passes_all_non_none_values(self) -> None:
        original = AsyncMock(return_value="ok")
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        await wrapped._arun(x=0, y="", z=False)

        # 0, empty string, False are NOT None — should be passed through
        original.assert_awaited_once_with(x=0, y="", z=False)

    async def test_empty_kwargs_still_calls_original(self) -> None:
        original = AsyncMock(return_value="ok")
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        await wrapped._arun()

        original.assert_awaited_once_with()

    async def test_returns_original_result_on_success(self) -> None:
        original = AsyncMock(return_value={"data": [1, 2, 3]})
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        result = await wrapped._arun(q="test")

        assert result == {"data": [1, 2, 3]}

    # --- Auth error re-raise ---

    async def test_reraises_401_error(self) -> None:
        original = AsyncMock(side_effect=Exception("HTTP 401 Unauthorized"))
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        with pytest.raises(Exception, match="401"):
            await wrapped._arun()

    async def test_reraises_unauthorized_error_case_insensitive(self) -> None:
        original = AsyncMock(side_effect=Exception("Access Unauthorized for user"))
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        with pytest.raises(Exception, match="Unauthorized"):
            await wrapped._arun()

    # --- Connection error callback ---

    @pytest.mark.parametrize(
        "error_pattern",
        [
            "timeout",
            "Connection Reset by peer",
            "Broken Pipe occurred",
            "Unexpected EOF while reading",
            "EOFError in stream",
            "Connection Refused on port 8080",
            "Connection Closed unexpectedly",
            "Server Disconnected",
            "Connect call failed",
            "Network Unreachable",
            "No route to host",
            "Not Connected to server",
            "Session Closed",
            "Session Expired",
            "SSL handshake failed",
            "Certificate verify failed",
        ],
    )
    async def test_connection_error_triggers_callback(self, error_pattern: str) -> None:
        original = AsyncMock(side_effect=Exception(error_pattern))
        tool = _make_tool(arun=original)
        callback = MagicMock()

        wrapped = wrap_tool_with_null_filter(tool, on_connection_error=callback)
        result = await wrapped._arun()

        callback.assert_called_once()
        assert isinstance(result, str)

    async def test_connection_error_no_callback_still_returns_message(self) -> None:
        original = AsyncMock(side_effect=Exception("Connection Refused"))
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool, on_connection_error=None)
        result = await wrapped._arun()

        assert "MCP tool error" in result

    async def test_async_callback_raises_type_error(self) -> None:
        original = AsyncMock(side_effect=Exception("timeout occurred"))
        tool = _make_tool(arun=original)

        async def async_callback() -> None:
            pass

        wrapped = wrap_tool_with_null_filter(tool, on_connection_error=async_callback)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="synchronous callable"):
            await wrapped._arun()

    # --- User-friendly error messages ---

    async def test_undefined_property_error_message(self) -> None:
        original = AsyncMock(
            side_effect=Exception("Cannot read properties of undefined (reading 'foo')")
        )
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        result = await wrapped._arun()

        assert "internal error" in result
        assert "bug in the MCP server" in result

    async def test_timeout_error_message(self) -> None:
        original = AsyncMock(side_effect=Exception("Request timeout after 30s"))
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        result = await wrapped._arun()

        assert "timed out" in result
        assert "try again" in result.lower()

    async def test_generic_error_returns_mcp_tool_error(self) -> None:
        original = AsyncMock(side_effect=Exception("Something completely unexpected"))
        tool = _make_tool(arun=original)

        wrapped = wrap_tool_with_null_filter(tool)
        result = await wrapped._arun()

        assert result == "MCP tool error: Something completely unexpected"

    async def test_returned_tool_is_same_object(self) -> None:
        tool = _make_tool()
        returned = wrap_tool_with_null_filter(tool)
        assert returned is tool


# ---------------------------------------------------------------------------
# wrap_tools_with_null_filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWrapToolsWithNullFilter:
    """Tests for wrap_tools_with_null_filter — batch wrapper."""

    async def test_wraps_all_tools(self) -> None:
        tools = [_make_tool(name=f"tool_{i}") for i in range(3)]
        result = wrap_tools_with_null_filter(tools)
        assert len(result) == 3

    async def test_empty_list(self) -> None:
        result = wrap_tools_with_null_filter([])
        assert result == []

    async def test_callback_propagated_to_all(self) -> None:
        callback = MagicMock()
        tools = [
            _make_tool(name="t1", arun=AsyncMock(side_effect=Exception("timeout"))),
            _make_tool(name="t2", arun=AsyncMock(side_effect=Exception("timeout"))),
        ]
        wrapped = wrap_tools_with_null_filter(tools, on_connection_error=callback)

        await wrapped[0]._arun()
        await wrapped[1]._arun()

        assert callback.call_count == 2


# ---------------------------------------------------------------------------
# extract_type_from_field
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractTypeFromField:
    """Tests for extract_type_from_field — JSON Schema → Python type."""

    # --- Basic types ---

    @pytest.mark.parametrize(
        "json_type,expected_python_type",
        [
            ("string", str),
            ("integer", int),
            ("number", float),
            ("boolean", bool),
            ("array", list),
            ("object", dict),
        ],
    )
    def test_basic_types(self, json_type: str, expected_python_type: type) -> None:
        field = {"type": json_type}
        python_type, default, is_optional = extract_type_from_field(field)
        assert python_type is expected_python_type
        assert default is None
        assert is_optional is False

    def test_unknown_type_returns_any(self) -> None:
        field: dict[str, object] = {"type": "custom_unknown"}
        python_type, _, _ = extract_type_from_field(field)
        assert python_type is Any

    def test_missing_type_defaults_to_string(self) -> None:
        field: dict[str, object] = {}
        python_type, _, _ = extract_type_from_field(field)
        assert python_type is str

    # --- Default values ---

    def test_default_value_returned(self) -> None:
        field = {"type": "number", "default": 50}
        _, default, _ = extract_type_from_field(field)
        assert default == 50

    def test_default_none(self) -> None:
        field = {"type": "string"}
        _, default, _ = extract_type_from_field(field)
        assert default is None

    # --- Enum types ---

    def test_enum_returns_literal(self) -> None:
        field = {"type": "string", "enum": ["low", "medium", "high"]}
        python_type, _, is_optional = extract_type_from_field(field)
        # Literal type should contain the enum values
        assert hasattr(python_type, "__args__")
        assert set(python_type.__args__) == {"low", "medium", "high"}
        assert is_optional is False

    def test_enum_with_default(self) -> None:
        field = {"type": "string", "enum": ["a", "b"], "default": "a"}
        python_type, default, _ = extract_type_from_field(field)
        assert default == "a"
        assert hasattr(python_type, "__args__")

    def test_empty_enum_list_falls_through(self) -> None:
        field = {"type": "integer", "enum": []}
        python_type, _, _ = extract_type_from_field(field)
        assert python_type is int

    def test_enum_non_list_falls_through(self) -> None:
        field = {"type": "string", "enum": "not_a_list"}
        python_type, _, _ = extract_type_from_field(field)
        assert python_type is str

    # --- anyOf (nullable types) ---

    def test_anyof_nullable_number(self) -> None:
        field = {"anyOf": [{"type": "number"}, {"type": "null"}], "default": 50}
        python_type, default, is_optional = extract_type_from_field(field)
        assert is_optional is True
        assert default == 50

    def test_anyof_nullable_string_no_default(self) -> None:
        field = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        python_type, default, is_optional = extract_type_from_field(field)
        assert is_optional is True
        assert default is None
        # When optional with no default, type becomes Union[str, None]
        assert python_type == Union[str, None]

    def test_anyof_with_enum_in_option(self) -> None:
        field = {
            "anyOf": [
                {"type": "string", "enum": ["red", "blue"]},
                {"type": "null"},
            ]
        }
        python_type, _, is_optional = extract_type_from_field(field)
        assert is_optional is True
        assert hasattr(python_type, "__args__")
        assert set(python_type.__args__) == {"red", "blue"}

    def test_anyof_empty_list_falls_through(self) -> None:
        field = {"anyOf": [], "type": "boolean"}
        python_type, _, is_optional = extract_type_from_field(field)
        assert python_type is bool
        assert is_optional is False

    # --- Type as list (JSON Schema variant) ---

    def test_type_list_with_null(self) -> None:
        field = {"type": ["string", "null"]}
        python_type, _, is_optional = extract_type_from_field(field)
        assert is_optional is True
        assert python_type == Union[str, None]

    def test_type_list_without_null(self) -> None:
        field = {"type": ["integer"]}
        python_type, _, is_optional = extract_type_from_field(field)
        assert is_optional is False
        assert python_type is int

    def test_type_list_only_null(self) -> None:
        field = {"type": ["null"]}
        python_type, _, is_optional = extract_type_from_field(field)
        assert is_optional is True
        # Falls back to "string" when no non-null type found
        assert python_type == Union[str, None]


# ---------------------------------------------------------------------------
# serialize_args_schema
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeArgsSchema:
    """Tests for serialize_args_schema — serializes a tool's args_schema."""

    def test_valid_basemodel_schema(self) -> None:
        class MyArgs(BaseModel):
            query: str
            count: int = 10

        tool = MagicMock(spec=BaseTool)
        tool.name = "searcher"
        tool.args_schema = MyArgs

        result = serialize_args_schema(tool)

        assert result is not None
        assert "properties" in result
        assert "required" in result
        assert "query" in result["properties"]
        assert "count" in result["properties"]

    def test_no_args_schema_attribute(self) -> None:
        tool = MagicMock(spec=[])  # no attributes at all
        tool.name = "bare_tool"
        # Ensure hasattr returns False for args_schema
        assert not hasattr(tool, "args_schema")
        result = serialize_args_schema(tool)
        assert result is None

    def test_args_schema_is_none(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "no_schema"
        tool.args_schema = None

        result = serialize_args_schema(tool)
        assert result is None

    def test_args_schema_is_not_basemodel_subclass(self) -> None:
        tool = MagicMock(spec=BaseTool)
        tool.name = "bad_schema"
        tool.args_schema = "not_a_class"

        result = serialize_args_schema(tool)
        assert result is None

    def test_args_schema_is_class_but_not_basemodel(self) -> None:
        class NotAModel:
            pass

        tool = MagicMock(spec=BaseTool)
        tool.name = "wrong_type"
        tool.args_schema = NotAModel

        result = serialize_args_schema(tool)
        assert result is None

    def test_model_json_schema_raises_exception(self) -> None:
        broken_model = MagicMock()
        broken_model.model_json_schema = MagicMock(
            side_effect=RuntimeError("schema broken")
        )

        tool = MagicMock(spec=BaseTool)
        tool.name = "broken"
        # Trick isinstance: args_schema must be a type subclassing BaseModel
        # We have to use a real BaseModel that raises on schema generation
        # Instead, we can patch issubclass to test the exception path

        class BreakingModel(BaseModel):
            pass

        # Patch the model_json_schema to raise
        with patch.object(
            BreakingModel, "model_json_schema", side_effect=RuntimeError("boom")
        ):
            tool.args_schema = BreakingModel
            result = serialize_args_schema(tool)
            assert result is None

    def test_schema_with_no_required_fields(self) -> None:
        class OptionalArgs(BaseModel):
            name: str = "default"

        tool = MagicMock(spec=BaseTool)
        tool.name = "optional_tool"
        tool.args_schema = OptionalArgs

        result = serialize_args_schema(tool)
        assert result is not None
        assert result["required"] == []
        assert "name" in result["properties"]


# ---------------------------------------------------------------------------
# _CONNECTION_ERROR_PATTERNS sanity check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnectionErrorPatterns:
    """Verify the constant tuple is non-empty and contains expected entries."""

    def test_is_non_empty_tuple(self) -> None:
        assert isinstance(_CONNECTION_ERROR_PATTERNS, tuple)
        assert len(_CONNECTION_ERROR_PATTERNS) > 0

    def test_all_entries_are_lowercase(self) -> None:
        for pattern in _CONNECTION_ERROR_PATTERNS:
            assert pattern == pattern.lower(), f"Pattern not lowercase: {pattern}"

    @pytest.mark.parametrize(
        "expected",
        ["timeout", "connection refused", "ssl", "broken pipe", "eof error"],
    )
    def test_contains_key_patterns(self, expected: str) -> None:
        assert expected in _CONNECTION_ERROR_PATTERNS
