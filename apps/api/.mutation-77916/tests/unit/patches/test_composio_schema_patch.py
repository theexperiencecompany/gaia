"""Tests for the Composio CustomTool schema-inlining patch.

``composio_custom_tool_schema_patch`` replaces ``CustomTool.__parse_info``
(the private, name-mangled attribute) with a wrapper that resolves every
``$ref`` in ``input_parameters`` via jsonref and converts the jsonref proxies
back to plain dicts, so schemas reach the LLM fully inlined.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from composio.core.models.custom_tools import CustomTool
import jsonref
import pytest

# Importing the patch module triggers the monkey-patch at import time.
import app.patches.composio_custom_tool_schema_patch as patch_module

_PRIVATE_PARSE_INFO = "_CustomTool__parse_info"

_REF_SCHEMA: dict = {
    "properties": {"a": {"$ref": "#/definitions/x"}},
    "definitions": {"x": {"type": "string"}},
}


def _call_patched(tool_info: object) -> object:
    """Invoke the patched parse_info with a stubbed original.

    The wrapper reads ``_original_parse_info`` at call time; re-point it at a
    stub so we exercise the wrapper in isolation, then restore it so we don't
    pollute other tests.
    """
    saved = patch_module._original_parse_info
    patch_module._original_parse_info = MagicMock(return_value=tool_info)
    try:
        return patch_module._patched_parse_info(MagicMock())
    finally:
        patch_module._original_parse_info = saved


class TestToStdDict:
    def test_converts_jsonref_proxies_to_plain_dicts(self) -> None:
        resolved = jsonref.replace_refs(_REF_SCHEMA)
        assert isinstance(resolved["properties"]["a"], jsonref.JsonRef)

        std = patch_module.to_std_dict(resolved)
        assert isinstance(std, dict)
        assert not isinstance(std["properties"]["a"], jsonref.JsonRef)
        assert std["properties"]["a"] == {"type": "string"}

    def test_recurses_through_lists_and_nested_dicts(self) -> None:
        resolved = jsonref.replace_refs(_REF_SCHEMA)
        nested = {"items": [resolved], "deep": {"inner": resolved}}
        std = patch_module.to_std_dict(nested)
        assert type(std["items"]) is list
        assert type(std["items"][0]["properties"]["a"]) is dict
        assert type(std["deep"]["inner"]["properties"]["a"]) is dict

    def test_scalars_pass_through_unchanged(self) -> None:
        for value in (42, "x", True, None, 3.5):
            result = patch_module.to_std_dict(value)
            assert result == value
            assert type(result) is type(value)


class TestPatchedParseInfo:
    def test_inlines_refs_in_input_parameters(self) -> None:
        tool_info = MagicMock(input_parameters=_REF_SCHEMA)
        result = _call_patched(tool_info)
        assert result is tool_info
        assert tool_info.input_parameters["properties"]["a"] == {"type": "string"}
        assert tool_info.input_parameters["definitions"]["x"] == {"type": "string"}

    def test_tool_info_without_input_parameters_returned_unchanged(self) -> None:
        tool_info = object()
        assert _call_patched(tool_info) is tool_info

    def test_non_dict_input_parameters_left_untouched(self) -> None:
        for value in (None, "plain string"):
            tool_info = MagicMock(input_parameters=value)
            result = _call_patched(tool_info)
            assert result is tool_info
            assert tool_info.input_parameters is value

    def test_raises_if_apply_was_never_called(self) -> None:
        saved = patch_module._original_parse_info
        patch_module._original_parse_info = None
        try:
            with pytest.raises(RuntimeError, match="apply"):
                patch_module._patched_parse_info(MagicMock())
        finally:
            patch_module._original_parse_info = saved


class TestApply:
    def test_private_parse_info_coupling_point_still_exists(self) -> None:
        # Tripwire: if Composio renames/removes the private method, the patch
        # import would already have raised. This asserts the coupling point.
        assert hasattr(CustomTool, _PRIVATE_PARSE_INFO)

    def test_patched_method_is_bound_to_custom_tool(self) -> None:
        assert getattr(CustomTool, _PRIVATE_PARSE_INFO) is patch_module._patched_parse_info

    def test_apply_is_idempotent(self) -> None:
        patch_module.apply()
        assert patch_module._applied is True
        assert getattr(CustomTool, _PRIVATE_PARSE_INFO) is patch_module._patched_parse_info
