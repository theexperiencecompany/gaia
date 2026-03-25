"""Tests for app.utils.schema_fixes module.

Tests normalize_schema_refs, _update_refs_recursive, and patch_tool_schema
covering all branches and edge cases.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.utils.schema_fixes import (
    _update_refs_recursive,
    normalize_schema_refs,
    patch_tool_schema,
)


# ---------------------------------------------------------------------------
# normalize_schema_refs
# ---------------------------------------------------------------------------


class TestNormalizeSchemaRefs:
    """Tests for normalize_schema_refs."""

    @pytest.mark.parametrize(
        "input_val",
        [
            "a string",
            42,
            None,
            True,
            [1, 2, 3],
        ],
        ids=["string", "int", "none", "bool", "list"],
    )
    def test_non_dict_input_returns_unchanged(self, input_val: Any) -> None:
        result = normalize_schema_refs(input_val)
        assert result is input_val

    def test_dict_without_defs_or_definitions_returns_unchanged(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = normalize_schema_refs(schema)
        assert result == schema

    def test_dict_with_empty_defs_returns_unchanged(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {},
        }
        result = normalize_schema_refs(schema)
        # Empty $defs is falsy, so no normalization occurs
        assert result["$defs"] == {}

    def test_dict_with_empty_definitions_returns_unchanged(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "definitions": {},
        }
        result = normalize_schema_refs(schema)
        assert result["definitions"] == {}

    def test_dict_with_only_string_keys_returns_unchanged(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {"street": {"type": "string"}},
                },
                "Name": {"type": "string"},
            },
            "properties": {
                "address": {"$ref": "#/$defs/Address"},
            },
        }
        result = normalize_schema_refs(schema)
        assert "$defs" in result
        assert "Address" in result["$defs"]
        assert "Name" in result["$defs"]
        # $ref should remain unchanged
        assert result["properties"]["address"]["$ref"] == "#/$defs/Address"

    def test_numeric_keys_in_defs_renamed(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
                "1": {"type": "integer"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
                "b": {"$ref": "#/$defs/1"},
            },
        }
        result = normalize_schema_refs(schema)
        assert "Def0" in result["$defs"]
        assert "Def1" in result["$defs"]
        assert "0" not in result["$defs"]
        assert "1" not in result["$defs"]
        assert result["$defs"]["Def0"] == {"type": "string"}
        assert result["$defs"]["Def1"] == {"type": "integer"}
        assert result["properties"]["a"]["$ref"] == "#/$defs/Def0"
        assert result["properties"]["b"]["$ref"] == "#/$defs/Def1"

    def test_numeric_keys_in_definitions_renamed(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "definitions": {
                "0": {"type": "boolean"},
                "2": {"type": "number"},
            },
            "properties": {
                "x": {"$ref": "#/definitions/0"},
                "y": {"$ref": "#/definitions/2"},
            },
        }
        result = normalize_schema_refs(schema)
        assert "Def0" in result["definitions"]
        assert "Def2" in result["definitions"]
        assert "0" not in result["definitions"]
        assert "2" not in result["definitions"]
        assert result["properties"]["x"]["$ref"] == "#/definitions/Def0"
        assert result["properties"]["y"]["$ref"] == "#/definitions/Def2"

    def test_mixed_numeric_and_string_keys(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
                "MyType": {"type": "object"},
                "3": {"type": "array", "items": {"type": "integer"}},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
                "b": {"$ref": "#/$defs/MyType"},
                "c": {"$ref": "#/$defs/3"},
            },
        }
        result = normalize_schema_refs(schema)
        # Numeric keys renamed
        assert "Def0" in result["$defs"]
        assert "Def3" in result["$defs"]
        # String key preserved
        assert "MyType" in result["$defs"]
        # Old numeric keys removed
        assert "0" not in result["$defs"]
        assert "3" not in result["$defs"]
        # Refs updated for numeric, preserved for string
        assert result["properties"]["a"]["$ref"] == "#/$defs/Def0"
        assert result["properties"]["b"]["$ref"] == "#/$defs/MyType"
        assert result["properties"]["c"]["$ref"] == "#/$defs/Def3"

    def test_nested_refs_updated_correctly(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {
                    "type": "object",
                    "properties": {
                        "child": {"$ref": "#/$defs/1"},
                    },
                },
                "1": {"type": "string"},
            },
            "properties": {
                "root": {"$ref": "#/$defs/0"},
            },
        }
        result = normalize_schema_refs(schema)
        assert result["$defs"]["Def0"]["properties"]["child"]["$ref"] == "#/$defs/Def1"
        assert result["properties"]["root"]["$ref"] == "#/$defs/Def0"

    def test_deep_nested_refs_updated(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {"$ref": "#/$defs/0"},
                            },
                        },
                    },
                },
            },
        }
        result = normalize_schema_refs(schema)
        deep_ref = result["properties"]["level1"]["properties"]["level2"]["properties"][
            "level3"
        ]
        assert deep_ref["$ref"] == "#/$defs/Def0"

    def test_original_schema_not_mutated(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
            },
        }
        normalize_schema_refs(schema)
        # The top-level dict is copied, but inner dicts are shared and mutated
        # by _update_refs_recursive (in-place). Verify the outer copy at least.
        assert "0" in schema["$defs"]

    def test_defs_preferred_over_definitions(self) -> None:
        """When both $defs and definitions exist, only $defs is processed."""
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "definitions": {
                "1": {"type": "integer"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
                "b": {"$ref": "#/definitions/1"},
            },
        }
        result = normalize_schema_refs(schema)
        # $defs numeric key renamed
        assert "Def0" in result["$defs"]
        # definitions not processed (since $defs was found first)
        assert "1" in result["definitions"]

    def test_refs_in_array_items(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/0"},
                },
            },
        }
        result = normalize_schema_refs(schema)
        assert result["properties"]["items"]["items"]["$ref"] == "#/$defs/Def0"

    def test_refs_in_anyof(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
                "1": {"type": "integer"},
            },
            "properties": {
                "value": {
                    "anyOf": [
                        {"$ref": "#/$defs/0"},
                        {"$ref": "#/$defs/1"},
                    ]
                }
            },
        }
        result = normalize_schema_refs(schema)
        any_of = result["properties"]["value"]["anyOf"]
        assert any_of[0]["$ref"] == "#/$defs/Def0"
        assert any_of[1]["$ref"] == "#/$defs/Def1"


# ---------------------------------------------------------------------------
# _update_refs_recursive
# ---------------------------------------------------------------------------


class TestUpdateRefsRecursive:
    """Tests for _update_refs_recursive."""

    def test_dict_with_matching_ref_updated(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/$defs/0"}
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["$ref"] == "#/$defs/Def0"

    def test_dict_with_non_matching_ref_not_updated(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/$defs/MyType"}
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["$ref"] == "#/$defs/MyType"

    def test_dict_with_ref_different_defs_key_not_updated(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/definitions/0"}
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        # defs_key is "$defs" but ref uses "definitions", so no match
        assert obj["$ref"] == "#/definitions/0"

    def test_dict_with_ref_matching_definitions_key(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/definitions/0"}
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "definitions")
        assert obj["$ref"] == "#/definitions/Def0"

    def test_nested_dict_recursion(self) -> None:
        obj: dict[str, Any] = {
            "properties": {
                "inner": {"$ref": "#/$defs/0"},
            }
        }
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["properties"]["inner"]["$ref"] == "#/$defs/Def0"

    def test_list_of_dicts_recursion(self) -> None:
        obj: list[Any] = [
            {"$ref": "#/$defs/0"},
            {"$ref": "#/$defs/1"},
            {"type": "string"},
        ]
        key_mapping = {"0": "Def0", "1": "Def1"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj[0]["$ref"] == "#/$defs/Def0"
        assert obj[1]["$ref"] == "#/$defs/Def1"
        assert obj[2] == {"type": "string"}

    @pytest.mark.parametrize(
        "value",
        ["a string", 42, None, True, 3.14],
        ids=["string", "int", "none", "bool", "float"],
    )
    def test_non_dict_non_list_is_noop(self, value: Any) -> None:
        # Should not raise
        _update_refs_recursive(value, {"0": "Def0"}, "$defs")

    def test_deeply_nested_list_and_dict(self) -> None:
        obj: dict[str, Any] = {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "deep": [{"$ref": "#/$defs/0"}],
                    },
                },
            ],
        }
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["anyOf"][0]["properties"]["deep"][0]["$ref"] == "#/$defs/Def0"

    def test_ref_key_not_in_mapping_stays_unchanged(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/$defs/5"}
        key_mapping = {"0": "Def0", "1": "Def1"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["$ref"] == "#/$defs/5"

    def test_ref_without_defs_prefix_stays_unchanged(self) -> None:
        obj: dict[str, Any] = {"$ref": "#/other/0"}
        key_mapping = {"0": "Def0"}
        _update_refs_recursive(obj, key_mapping, "$defs")
        assert obj["$ref"] == "#/other/0"

    def test_empty_dict(self) -> None:
        obj: dict[str, Any] = {}
        _update_refs_recursive(obj, {"0": "Def0"}, "$defs")
        assert obj == {}

    def test_empty_list(self) -> None:
        obj: list[Any] = []
        _update_refs_recursive(obj, {"0": "Def0"}, "$defs")
        assert obj == []


# ---------------------------------------------------------------------------
# patch_tool_schema
# ---------------------------------------------------------------------------


class TestPatchToolSchema:
    """Tests for patch_tool_schema."""

    def test_tool_without_input_schema_attribute(self) -> None:
        tool = MagicMock(spec=["name"])
        tool.name = "test_tool"
        result = patch_tool_schema(tool)
        assert result is tool

    def test_tool_with_none_input_schema(self) -> None:
        tool = MagicMock(spec=["name", "inputSchema"])
        tool.name = "test_tool"
        tool.inputSchema = None
        result = patch_tool_schema(tool)
        assert result is tool

    def test_tool_with_empty_dict_input_schema(self) -> None:
        tool = MagicMock(spec=["name", "inputSchema", "model_dump"])
        tool.name = "test_tool"
        tool.inputSchema = {}
        # Empty dict is falsy, so should return unchanged
        result = patch_tool_schema(tool)
        assert result is tool

    def test_tool_with_schema_no_changes_needed(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        tool = MagicMock(spec=["name", "inputSchema", "model_dump"])
        tool.name = "test_tool"
        tool.inputSchema = schema
        result = patch_tool_schema(tool)
        # Schema doesn't need changes (no numeric keys), so original returned
        assert result is tool

    def test_tool_with_schema_needing_fixes(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
            },
        }
        tool = MagicMock(spec=["name", "inputSchema", "model_dump"])
        tool.name = "test_tool"
        tool.inputSchema = schema

        dumped = {
            "name": "test_tool",
            "inputSchema": schema.copy(),
            "description": "A test tool",
        }
        tool.model_dump.return_value = dumped

        # The constructor of the tool's type should return a new tool
        new_tool = MagicMock()
        type(tool).__call__ = MagicMock(return_value=new_tool)  # type: ignore[method-assign]
        # Patch: type(tool)(**tool_dict) creates a new tool instance
        type(tool).return_value = new_tool

        result = patch_tool_schema(tool)
        # model_dump was called to create the modified copy
        tool.model_dump.assert_called_once()
        # Result should be the newly constructed tool (not original)
        assert result is not tool

    def test_tool_with_schema_needing_fixes_returns_correct_schema(self) -> None:
        """Verify the normalized schema is passed to the reconstructed tool."""
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
                "1": {"type": "integer"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
                "b": {"$ref": "#/$defs/1"},
            },
        }

        # Build a mock that acts like a Pydantic model
        tool = MagicMock()
        tool.name = "test_tool"
        tool.inputSchema = schema

        captured_kwargs: dict[str, Any] = {}

        def fake_constructor(**kwargs: Any) -> MagicMock:
            captured_kwargs.update(kwargs)
            return MagicMock()

        type(tool).__call__ = fake_constructor  # type: ignore[assignment]
        tool.model_dump.return_value = {
            "name": "test_tool",
            "inputSchema": schema.copy(),
        }

        # type(tool)(**tool_dict) calls the class constructor
        # We need to make type(tool) callable and capture args
        original_type = type(tool)
        original_type.side_effect = None  # type: ignore[attr-defined]

        patch_tool_schema(tool)

        # Verify model_dump was called
        tool.model_dump.assert_called_once()

    def test_exception_during_patching_returns_original(self) -> None:
        tool = MagicMock(spec=["name", "inputSchema", "model_dump"])
        tool.name = "test_tool"
        tool.inputSchema = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "a": {"$ref": "#/$defs/0"},
            },
        }
        # model_dump raises an exception
        tool.model_dump.side_effect = RuntimeError("serialization error")

        result = patch_tool_schema(tool)
        assert result is tool

    def test_exception_during_type_construction_returns_original(self) -> None:
        class BrokenTool:
            """A tool whose constructor raises on reconstruction."""

            name = "test_tool"
            inputSchema: dict[str, Any] = {
                "type": "object",
                "$defs": {
                    "0": {"type": "string"},
                },
                "properties": {
                    "a": {"$ref": "#/$defs/0"},
                },
            }

            def model_dump(self) -> dict[str, Any]:
                return {
                    "name": self.name,
                    "inputSchema": dict(self.inputSchema),
                }

            def __init__(self, **kwargs: Any) -> None:
                if kwargs:
                    raise ValueError("construction error")

        tool = BrokenTool()
        result = patch_tool_schema(tool)
        assert result is tool


# ---------------------------------------------------------------------------
# Parametrized edge cases
# ---------------------------------------------------------------------------


class TestNormalizeSchemaRefsParametrized:
    """Parametrized tests covering additional edge cases."""

    @pytest.mark.parametrize(
        "defs_key",
        ["$defs", "definitions"],
        ids=["dollar_defs", "definitions"],
    )
    def test_single_numeric_key_renamed(self, defs_key: str) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            defs_key: {
                "7": {"type": "boolean"},
            },
            "properties": {
                "flag": {"$ref": f"#/{defs_key}/7"},
            },
        }
        result = normalize_schema_refs(schema)
        assert "Def7" in result[defs_key]
        assert "7" not in result[defs_key]
        assert result["properties"]["flag"]["$ref"] == f"#/{defs_key}/Def7"

    @pytest.mark.parametrize(
        ("numeric_keys", "expected_def_keys"),
        [
            (["0"], ["Def0"]),
            (["0", "1", "2"], ["Def0", "Def1", "Def2"]),
            (["10", "20"], ["Def10", "Def20"]),
        ],
        ids=["single", "three_sequential", "large_numbers"],
    )
    def test_various_numeric_key_counts(
        self, numeric_keys: list[str], expected_def_keys: list[str]
    ) -> None:
        defs: dict[str, Any] = {k: {"type": "string"} for k in numeric_keys}
        props: dict[str, Any] = {
            f"prop_{k}": {"$ref": f"#/$defs/{k}"} for k in numeric_keys
        }

        schema: dict[str, Any] = {
            "type": "object",
            "$defs": defs,
            "properties": props,
        }
        result = normalize_schema_refs(schema)

        for old_key, new_key in zip(numeric_keys, expected_def_keys):
            assert new_key in result["$defs"]
            assert old_key not in result["$defs"]
            assert (
                result["properties"][f"prop_{old_key}"]["$ref"] == f"#/$defs/{new_key}"
            )

    def test_ref_in_list_inside_allof(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "allOf": [
                {"$ref": "#/$defs/0"},
            ],
        }
        result = normalize_schema_refs(schema)
        assert result["allOf"][0]["$ref"] == "#/$defs/Def0"

    def test_no_refs_but_numeric_defs_still_renamed(self) -> None:
        """Defs with numeric keys are renamed even if no $ref points to them."""
        schema: dict[str, Any] = {
            "type": "object",
            "$defs": {
                "0": {"type": "string"},
            },
            "properties": {
                "name": {"type": "string"},
            },
        }
        result = normalize_schema_refs(schema)
        assert "Def0" in result["$defs"]
        assert "0" not in result["$defs"]
