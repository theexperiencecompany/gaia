"""
Unit tests for MCP utility functions.

Tests cover:
- PKCE pair generation (code_verifier and code_challenge)
- Tool null value filtering
- Tool schema serialization
- JSON Schema type extraction
"""

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.utils.mcp_utils import (
    extract_type_from_field,
    generate_pkce_pair,
    serialize_args_schema,
    wrap_tool_with_null_filter,
    wrap_tools_with_null_filter,
)


# ==============================================================================
# PKCE Generation Tests
# ==============================================================================


class TestGeneratePkcePair:
    """Tests for generate_pkce_pair function."""

    def test_generates_valid_code_verifier(self):
        """Code verifier should be URL-safe base64."""
        code_verifier, _ = generate_pkce_pair()

        # Should be non-empty
        assert len(code_verifier) > 0

        # Should be URL-safe (no +, /, or = characters that aren't padding)
        assert "+" not in code_verifier
        assert "/" not in code_verifier

    def test_generates_valid_code_challenge(self):
        """Code challenge should be S256 hash of code verifier."""
        code_verifier, code_challenge = generate_pkce_pair()

        # Compute expected challenge
        digest = hashlib.sha256(code_verifier.encode()).digest()
        expected_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

        assert code_challenge == expected_challenge

    def test_generates_unique_pairs(self):
        """Each call should generate a unique pair."""
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()

        assert pair1[0] != pair2[0]  # Different verifiers
        assert pair1[1] != pair2[1]  # Different challenges

    def test_code_verifier_length(self):
        """Code verifier should be sufficiently long for security."""
        code_verifier, _ = generate_pkce_pair()

        # RFC 7636 requires 43-128 characters
        # Our implementation uses 43 characters (32 bytes base64 encoded)
        assert len(code_verifier) >= 43


# ==============================================================================
# Tool Null Filter Tests
# ==============================================================================


class TestWrapToolWithNullFilter:
    """Tests for wrap_tool_with_null_filter function."""

    @pytest.mark.asyncio
    async def test_filters_none_values(self):
        """Should filter out None values before calling tool."""
        # Track what arguments were passed to the original _arun
        call_args = []

        async def mock_arun(**kwargs):
            call_args.append(kwargs)
            return "result"

        # Create a mock tool with a real async function
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = mock_arun

        # Wrap the tool
        wrapped = wrap_tool_with_null_filter(mock_tool)

        # Call with None values
        await wrapped._arun(param1="value1", param2=None, param3="value3")

        # Verify None was filtered
        assert len(call_args) == 1
        assert call_args[0] == {"param1": "value1", "param3": "value3"}

    @pytest.mark.asyncio
    async def test_preserves_non_none_values(self):
        """Should preserve all non-None values."""
        call_args = []

        async def mock_arun(**kwargs):
            call_args.append(kwargs)
            return "result"

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = mock_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        # Call with no None values
        await wrapped._arun(param1="value1", param2=0, param3=False, param4="")

        # All values should be preserved (0, False, "" are valid non-None values)
        assert len(call_args) == 1
        assert call_args[0] == {
            "param1": "value1",
            "param2": 0,
            "param3": False,
            "param4": "",
        }

    @pytest.mark.asyncio
    async def test_returns_original_result(self):
        """Should return the original tool's result."""
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = AsyncMock(return_value={"data": "test"})

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        assert result == {"data": "test"}


class TestWrapToolsWithNullFilter:
    """Tests for wrap_tools_with_null_filter function."""

    def test_wraps_multiple_tools(self):
        """Should wrap all tools in the list."""
        tools = []
        for i in range(3):
            mock_tool = MagicMock(spec=BaseTool)
            mock_tool.name = f"tool_{i}"
            mock_tool._arun = AsyncMock()
            tools.append(mock_tool)

        wrapped = wrap_tools_with_null_filter(tools)

        assert len(wrapped) == 3
        # Each tool should have been modified
        for i, tool in enumerate(wrapped):
            assert tool.name == f"tool_{i}"

    def test_empty_list_returns_empty(self):
        """Should return empty list for empty input."""
        result = wrap_tools_with_null_filter([])
        assert result == []


# ==============================================================================
# JSON Schema Type Extraction Tests
# ==============================================================================


class TestExtractTypeFromField:
    """Tests for extract_type_from_field function."""

    def test_extracts_string_type(self):
        """Should extract string type."""
        field_info = {"type": "string"}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is str
        assert default is None
        assert is_optional is False

    def test_extracts_integer_type(self):
        """Should extract integer type."""
        field_info = {"type": "integer", "default": 10}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is int
        assert default == 10
        assert is_optional is False

    def test_extracts_number_type(self):
        """Should extract number/float type."""
        field_info = {"type": "number"}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is float

    def test_extracts_boolean_type(self):
        """Should extract boolean type."""
        field_info = {"type": "boolean", "default": True}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is bool
        assert default is True

    def test_extracts_array_type(self):
        """Should extract array/list type."""
        field_info = {"type": "array"}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is list

    def test_extracts_object_type(self):
        """Should extract object/dict type."""
        field_info = {"type": "object"}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert python_type is dict

    def test_handles_anyof_nullable(self):
        """Should handle anyOf with null type (nullable field)."""
        field_info = {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "default": 50,
        }
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert default == 50
        assert is_optional is True

    def test_handles_type_array_with_null(self):
        """Should handle type array with null (legacy nullable syntax)."""
        field_info = {"type": ["string", "null"]}
        python_type, default, is_optional = extract_type_from_field(field_info)

        assert is_optional is True


# ==============================================================================
# Tool Schema Serialization Tests
# ==============================================================================


class TestSerializeArgsSchema:
    """Tests for serialize_args_schema function."""

    def test_serializes_pydantic_schema(self):
        """Should serialize Pydantic model schema."""

        class TestSchema(BaseModel):
            query: str = Field(description="Search query")
            limit: int = Field(default=10, description="Result limit")

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool.args_schema = TestSchema

        result = serialize_args_schema(mock_tool)

        assert result is not None
        assert "properties" in result
        assert "query" in result["properties"]
        assert "limit" in result["properties"]
        assert "required" in result

    def test_returns_none_for_no_schema(self):
        """Should return None when tool has no schema."""
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool.args_schema = None

        result = serialize_args_schema(mock_tool)

        assert result is None

    def test_returns_none_for_non_pydantic_schema(self):
        """Should return None for non-Pydantic schemas."""
        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool.args_schema = {"not": "a pydantic model"}

        result = serialize_args_schema(mock_tool)

        assert result is None


# ==============================================================================
# Tool Error Handling Tests
# ==============================================================================


class TestToolErrorHandling:
    """Tests for MCP tool error handling in wrap_tool_with_null_filter."""

    @pytest.mark.asyncio
    async def test_handles_undefined_property_error(self):
        """Should return user-friendly message for JavaScript undefined errors."""

        async def failing_arun(**kwargs):
            raise Exception("Cannot read properties of undefined (reading 'length')")

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = failing_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        assert "MCP server encountered an internal error" in result
        assert "undefined" in result

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self):
        """Should return user-friendly message for timeout errors."""

        async def failing_arun(**kwargs):
            raise Exception("Request timeout after 30000ms")

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = failing_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        assert "timed out" in result
        assert "try again" in result

    @pytest.mark.asyncio
    async def test_handles_auth_error(self):
        """Should return user-friendly message for auth errors."""

        async def failing_arun(**kwargs):
            raise Exception("HTTP 401 Unauthorized")

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = failing_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        assert "Authentication required" in result or "401" in result

    @pytest.mark.asyncio
    async def test_handles_generic_error(self):
        """Should return error message for generic errors."""

        async def failing_arun(**kwargs):
            raise Exception("Something went wrong")

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = failing_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        assert "MCP tool error" in result
        assert "Something went wrong" in result

    @pytest.mark.asyncio
    async def test_logs_error_results(self):
        """Should handle results that contain error messages."""

        async def error_result_arun(**kwargs):
            return "Error searching papers: API rate limit exceeded"

        mock_tool = MagicMock(spec=BaseTool)
        mock_tool.name = "test_tool"
        mock_tool._arun = error_result_arun

        wrapped = wrap_tool_with_null_filter(mock_tool)

        result = await wrapped._arun(query="test")

        # Should return the original error message
        assert "Error searching papers" in result
