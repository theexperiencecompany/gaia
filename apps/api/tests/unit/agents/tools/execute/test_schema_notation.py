"""schema_notation — the compact text a schema becomes in model context."""

from datetime import UTC, datetime

from pydantic import JsonValue
import pytest

from app.agents.tools.execute import schema_notation
from app.agents.tools.execute.schema_notation import (
    inline_local_refs,
    render_args_budgeted,
    render_compact_type,
    render_compact_type_budgeted,
)
from app.utils.general_utils import clip_text

UNBOUNDED = 10**9


def _deep_response_schema() -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "properties": {
                    f"field_{i}": {
                        "type": "object",
                        "properties": {"leaf": {"type": "string", "description": "y" * 200}},
                    }
                    for i in range(50)
                },
            }
        },
    }


def _nested(depth: int) -> dict[str, JsonValue]:
    """Build an object nested depth levels deep, named a, b, c, ... down to a string leaf."""
    node: dict[str, JsonValue] = {"type": "string"}
    for name in reversed("abcdefgh"[:depth]):
        node = {"type": "object", "properties": {name: node}}
    return node


def _args(
    properties: dict[str, JsonValue], required: list[str] | None = None
) -> dict[str, JsonValue]:
    schema: dict[str, JsonValue] = {"type": "object", "properties": properties}
    if required is not None:
        schema["required"] = list(required)
    return schema


@pytest.mark.unit
class TestCompactType:
    def test_core_shapes(self) -> None:
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "count": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["open", "closed"]},
                "parent": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "meta": {"type": "object"},
            },
            "required": ["id", "count"],
        }
        assert render_compact_type(schema) == (
            '{id:str, count:int, tags?:str[], status?:"open"|"closed", parent?:null|str, meta?:obj}'
        )

    def test_a_map_renders_as_an_index_signature(self) -> None:
        """Observed shapes store data-keyed maps as additionalProperties; the notation must show the value shape, not degrade the map to bare obj."""
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {
                "per_user": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {"n": {"type": "integer"}},
                        "required": ["n"],
                    },
                }
            },
            "required": ["per_user"],
        }
        assert render_compact_type(schema) == "{per_user:{[key]:{n:int}}}"

    def test_union_array_items_are_grouped(self) -> None:
        schema: dict[str, JsonValue] = {
            "type": "array",
            "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        }
        # Without grouping, {a}|{b}[] misreads as a union with an array arm.
        assert render_compact_type(schema) == "(int|str)[]"

    def test_local_refs_resolve_to_their_definition(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Item": {"type": "object", "properties": {"id": {"type": "string"}}}},
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}},
        }
        assert render_compact_type(schema) == "{items?:{id?:str}[]}"

    def test_a_python_enum_member_renders_as_json(self) -> None:
        when = datetime(2026, 1, 1, tzinfo=UTC)
        assert render_compact_type({"enum": [when]}) == '"2026-01-01 00:00:00+00:00"'

    @pytest.mark.parametrize(
        ("schema", "rendered"),
        [
            ({"type": "object", "properties": {"x": True}}, "{x?:any}"),
            ({"type": "date"}, "date"),
            ({}, "any"),
            ({"oneOf": [{"type": "string"}, {"type": "integer"}]}, "int|str"),
            ({"anyOf": [], "type": "string"}, "str"),
            ({"anyOf": {"type": "string"}, "type": "integer"}, "int"),
            ({"type": ["string", "null"]}, "null|str"),
            ({"properties": {"a": {"type": "string"}}}, "{a?:str}"),
            ({"type": "string", "enum": ["only"]}, '"only"'),
            ({"type": "string", "enum": []}, "str"),
            ({"type": "integer", "enum": [1, 2, 3, 4, 5, 6]}, "1|2|3|4|5|6"),
            ({"type": "integer", "enum": [1, 2, 3, 4, 5, 6, 7]}, "int"),
            ({"type": "string", "const": "text"}, '"text"'),
            ({"const": None}, "null"),
            ({"type": "number"}, "num"),
            ({"type": "boolean"}, "bool"),
            ({"anyOf": [{"type": "string"}, {}, {"type": "null"}]}, "null|str"),
            ({"anyOf": [{}, True]}, "any"),
            ({"anyOf": [{"type": "string"}, {}]}, "str"),
            ({"anyOf": [{"enum": ["a", "b"]}, {"type": "null"}]}, '"a"|"b"|null'),
            ({"type": "array", "items": {"enum": ["a", "b"]}}, '("a"|"b")[]'),
            ({"type": "object", "additionalProperties": {"enum": ["a"]}}, '{[key]:"a"}'),
            (
                {
                    "$defs": {"Id": {"type": "string"}},
                    "anyOf": [{"$ref": "#/$defs/Id"}, {"type": "null"}],
                },
                "null|str",
            ),
        ],
        ids=[
            "boolean_subschema",
            "unknown_type",
            "no_type",
            "one_of",
            "empty_any_of",
            "malformed_any_of",
            "type_list",
            "untyped_object",
            "single_member_enum",
            "empty_enum",
            "enum_at_the_cap",
            "enum_over_the_cap",
            "const",
            "null_const",
            "number",
            "boolean",
            "any_arm_beside_real_types",
            "only_any_arms",
            "any_arm_beside_one_type",
            "enum_in_a_union",
            "enum_items",
            "enum_map_values",
            "ref_in_a_union",
        ],
    )
    def test_shape(self, schema: dict[str, JsonValue], rendered: str) -> None:
        assert render_compact_type(schema) == rendered


@pytest.mark.unit
class TestBudgetedCompactType:
    def test_a_type_that_exactly_fits_is_returned_whole(self) -> None:
        assert render_compact_type_budgeted(_nested(1), len("{a?:str}")) == "{a?:str}"

    def test_a_depth_collapse_that_exactly_fits_is_taken(self) -> None:
        assert render_compact_type_budgeted(_nested(4), len("{a?:{b?:{c?:obj}}}")) == (
            "{a?:{b?:{c?:obj}}}\n(deeper fields omitted for size; the real data has them)"
        )

    def test_nothing_fitting_clips_the_full_rendering(self) -> None:
        full = render_compact_type(_nested(4))
        assert render_compact_type_budgeted(_nested(4), 3) == clip_text(full, 3)

    def test_an_oversized_shape_collapses_its_depth(self) -> None:
        rendered = render_compact_type_budgeted(_deep_response_schema(), 800)
        assert len(rendered.splitlines()[0]) <= 800
        assert "obj" in rendered
        assert "omitted for size" in rendered

    def test_enums_survive_the_full_and_the_pruned_render(self) -> None:
        schema: dict[str, JsonValue] = {
            "type": "object",
            "properties": {"s": {"enum": ["a", "b"]}, "deep": _nested(3)},
        }
        assert render_compact_type_budgeted(schema, UNBOUNDED) == (
            '{s?:"a"|"b", deep?:{a?:{b?:{c?:str}}}}'
        )
        pruned = '{s?:"a"|"b", deep?:{a?:{b?:obj}}}'
        assert render_compact_type_budgeted(schema, len(pruned)) == (
            f"{pruned}\n(deeper fields omitted for size; the real data has them)"
        )

    def test_refs_resolve_before_depth_is_counted(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"B": {"type": "object", "properties": {"c": {"type": "string"}}}},
            "type": "object",
            "properties": {"a": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}}},
        }
        assert render_compact_type_budgeted(schema, len("{a?:{b?:{c?:str}}}")) == (
            "{a?:{b?:{c?:str}}}"
        )


@pytest.mark.unit
class TestInlineLocalRefs:
    def test_a_ref_is_replaced_by_its_definition_and_defs_are_dropped(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Id": {"type": "string"}},
            "type": "object",
            "properties": {"id": {"$ref": "#/$defs/Id"}},
        }
        assert inline_local_refs(schema) == {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        }

    def test_definitions_is_read_like_defs(self) -> None:
        schema: dict[str, JsonValue] = {
            "definitions": {"Id": {"type": "integer"}},
            "properties": {"id": {"$ref": "#/definitions/Id"}},
        }
        assert inline_local_refs(schema) == {"properties": {"id": {"type": "integer"}}}

    def test_a_refs_own_description_overrides_the_definitions(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Id": {"type": "string", "description": "generic"}},
            "properties": {"id": {"$ref": "#/$defs/Id", "description": "the user's id"}},
        }
        assert inline_local_refs(schema)["properties"] == {
            "id": {"type": "string", "description": "the user's id"}
        }

    def test_a_ref_inside_a_definition_resolves_too(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {
                "Outer": {"type": "object", "properties": {"inner": {"$ref": "#/$defs/Inner"}}},
                "Inner": {"type": "boolean"},
            },
            "properties": {"o": {"$ref": "#/$defs/Outer"}},
        }
        assert render_compact_type(schema) == "{o?:{inner?:bool}}"

    def test_a_recursive_ref_stops_at_a_bare_object(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {
                "Step": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "steps": {"type": "array", "items": {"$ref": "#/$defs/Step"}},
                    },
                }
            },
            "type": "object",
            "properties": {"steps": {"type": "array", "items": {"$ref": "#/$defs/Step"}}},
        }
        assert render_compact_type(schema) == "{steps?:{tool?:str, steps?:obj[]}[]}"

    @pytest.mark.parametrize(
        "ref",
        ["#/$defs/Missing", "https://example.com/schema.json", "#/properties/x", 7],
        ids=["missing_definition", "remote", "non_definition_pointer", "not_a_string"],
    )
    def test_an_unresolvable_ref_is_dropped_and_its_siblings_kept(self, ref: JsonValue) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Id": {"type": "string"}},
            "properties": {"x": {"$ref": ref, "description": "kept"}},
        }
        assert inline_local_refs(schema) == {"properties": {"x": {"description": "kept"}}}

    def test_a_definition_that_is_not_an_object_leaves_the_siblings(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Flag": True},
            "properties": {"x": {"$ref": "#/$defs/Flag", "description": "kept"}},
        }
        assert inline_local_refs(schema) == {"properties": {"x": {"description": "kept"}}}


@pytest.mark.unit
class TestRenderArgs:
    def test_required_fields_are_bare_and_optional_fields_are_marked(self) -> None:
        schema = _args({"to": {"type": "string"}, "cc": {"type": "string"}}, ["to"])
        assert render_args_budgeted(schema, UNBOUNDED) == "to: str\ncc?: str"

    def test_a_description_and_its_constraints_share_one_comment(self) -> None:
        schema = _args(
            {
                "limit": {
                    "type": "integer",
                    "description": "How many\n   to fetch.",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 10,
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == (
            "limit?: int  # How many to fetch. [default: 10, minimum: 1, maximum: 500]"
        )

    @pytest.mark.parametrize(
        ("field", "comment"),
        [
            ({"type": "string", "default": "primary"}, '[default: "primary"]'),
            ({"type": "string", "format": "date-time"}, "[format: date-time]"),
            ({"type": "string", "pattern": "^\\d+$"}, "[pattern: ^\\d+$]"),
            ({"type": "number", "exclusiveMinimum": 0}, "[exclusiveMinimum: 0]"),
            ({"type": "number", "exclusiveMaximum": 1}, "[exclusiveMaximum: 1]"),
            ({"type": "string", "minLength": 1, "maxLength": 9}, "[minLength: 1, maxLength: 9]"),
            (
                {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                "[minItems: 1, maxItems: 5]",
            ),
            ({"type": "boolean", "default": False}, "[default: false]"),
            ({"type": "array", "default": []}, "[default: []]"),
            ({"type": "object", "default": {"a": 1, "b": [1, 2]}}, '[default: {"a":1,"b":[1,2]}]'),
            ({"type": "string", "default": None, "format": "email"}, "[format: email]"),
            ({"anyOf": [True, {"type": "string", "format": "date"}]}, "[format: date]"),
        ],
        ids=[
            "string_default_quoted",
            "format_bare",
            "pattern_bare",
            "exclusive_minimum",
            "exclusive_maximum",
            "length_bounds",
            "item_bounds",
            "false_default",
            "empty_list_default",
            "object_default_compact_json",
            "constraint_after_a_null_default",
            "constraint_after_a_non_schema_arm",
        ],
    )
    def test_each_constraint_renders(self, field: dict[str, JsonValue], comment: str) -> None:
        assert render_args_budgeted(_args({"f": field}), UNBOUNDED).endswith(f"  # {comment}")

    def test_a_null_default_and_examples_are_noise_and_never_render(self) -> None:
        schema = _args({"q": {"type": "string", "default": None, "examples": ["from:me"]}})
        assert render_args_budgeted(schema, UNBOUNDED) == "q?: str"

    def test_a_long_constraint_value_is_clipped(self) -> None:
        schema = _args({"q": {"type": "string", "pattern": "a" * 100}})
        assert (
            render_args_budgeted(schema, UNBOUNDED)
            == f"q?: str  # [pattern: {clip_text('a' * 100, 80)}]"
        )

    def test_constraints_inside_a_union_arm_still_render(self) -> None:
        """Pydantic writes Optional[datetime] as anyOf[{format: date-time}, null]: the format lives in the arm."""
        schema = _args(
            {"at": {"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]}}
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "at?: null|str  # [format: date-time]"

    def test_the_field_constraint_wins_over_the_arms(self) -> None:
        schema = _args(
            {
                "n": {
                    "default": 1,
                    "anyOf": [{"type": "integer", "default": 2}, {"type": "null"}],
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "n?: int|null  # [default: 1]"

    def test_args_enums_list_more_members_than_return_enums(self) -> None:
        members = [f"m{i}" for i in range(25)]
        schema = _args({"kind": {"type": "string", "enum": members}})
        assert render_args_budgeted(schema, UNBOUNDED) == "kind?: " + "|".join(
            f'"{m}"' for m in members
        )

    def test_a_root_enum_uses_the_args_cap(self) -> None:
        members = [f"m{i}" for i in range(7)]
        rendered = render_args_budgeted({"type": "string", "enum": members}, UNBOUNDED)
        assert rendered == "|".join(f'"{m}"' for m in members)

    def test_an_enum_past_the_args_cap_renders_its_base_type(self) -> None:
        schema = _args({"kind": {"type": "string", "enum": [f"m{i}" for i in range(26)]}})
        assert render_args_budgeted(schema, UNBOUNDED) == "kind?: str"

    def test_a_nested_object_nests_its_fields_as_indented_lines(self) -> None:
        schema = _args(
            {
                "event": {
                    "type": "object",
                    "description": "The event.",
                    "properties": {
                        "title": {"type": "string", "description": "Shown in the calendar."},
                        "where": {
                            "type": "object",
                            "properties": {"room": {"type": "string"}},
                            "required": ["room"],
                        },
                    },
                    "required": ["title"],
                }
            },
            ["event"],
        )
        assert render_args_budgeted(schema, UNBOUNDED).split("\n") == [
            "event: {  # The event.",
            "  title: str  # Shown in the calendar.",
            "  where?: {",
            "    room: str",
            "  }",
            "}",
        ]

    def test_an_array_of_objects_closes_with_brackets(self) -> None:
        schema = _args(
            {
                "rows": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "rows?: {\n  id?: int\n}[]"

    def test_a_nullable_object_nests_behind_its_other_arms(self) -> None:
        schema = _args(
            {
                "meta": {
                    "type": ["object", "null"],
                    "properties": {"k": {"type": "string"}},
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "meta?: null|{\n  k?: str\n}"

    def test_an_any_arm_never_prefixes_a_nested_object(self) -> None:
        schema = _args(
            {
                "meta": {
                    "anyOf": [
                        {"type": "object", "properties": {"k": {"type": "string"}}},
                        {},
                        {"type": "null"},
                    ]
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "meta?: null|{\n  k?: str\n}"

    def test_every_other_arm_prefixes_a_nested_object(self) -> None:
        members = [f"m{i}" for i in range(7)]
        schema = _args(
            {
                "v": {
                    "anyOf": [
                        {"type": "object", "properties": {"k": {"type": "string"}}},
                        {"type": "string", "enum": members},
                        {"type": "null"},
                    ]
                }
            }
        )
        enum = "|".join(f'"{m}"' for m in members)
        assert render_args_budgeted(schema, UNBOUNDED) == f"v?: {enum}|null|{{\n  k?: str\n}}"

    def test_a_union_of_two_objects_stays_inline(self) -> None:
        schema = _args(
            {
                "target": {
                    "anyOf": [
                        {"type": "object", "properties": {"id": {"type": "string"}}},
                        {"type": "object", "properties": {"url": {"type": "string"}}},
                    ]
                }
            }
        )
        assert render_args_budgeted(schema, UNBOUNDED) == "target?: {id?:str}|{url?:str}"

    def test_an_array_of_nullable_objects_stays_inline(self) -> None:
        item: dict[str, JsonValue] = {
            "anyOf": [
                {"type": "object", "properties": {"id": {"type": "string"}}},
                {"type": "null"},
            ]
        }
        schema = _args({"rows": {"type": "array", "items": item}})
        assert render_args_budgeted(schema, UNBOUNDED) == "rows?: (null|{id?:str})[]"

    def test_an_object_without_fields_stays_inline(self) -> None:
        schema = _args({"extra": {"type": "object", "additionalProperties": {"type": "string"}}})
        assert render_args_budgeted(schema, UNBOUNDED) == "extra?: {[key]:str}"

    def test_a_field_that_is_not_a_schema_renders_as_any(self) -> None:
        assert render_args_budgeted(_args({"x": True}), UNBOUNDED) == "x?: any"

    @pytest.mark.parametrize(
        ("schema", "rendered"),
        [
            ({"type": "object", "properties": {}}, "obj"),
            ({"type": "object", "additionalProperties": {"type": "integer"}}, "{[key]:int}"),
            ({"type": "string"}, "str"),
        ],
        ids=["no_fields", "map", "not_an_object"],
    )
    def test_a_schema_without_fields_renders_as_one_type(
        self, schema: dict[str, JsonValue], rendered: str
    ) -> None:
        assert render_args_budgeted(schema, UNBOUNDED) == rendered

    def test_refs_inline_into_nested_lines(self) -> None:
        schema: dict[str, JsonValue] = {
            "$defs": {"Who": {"type": "object", "properties": {"email": {"type": "string"}}}},
            "type": "object",
            "properties": {"to": {"$ref": "#/$defs/Who", "description": "Recipient."}},
        }
        assert render_args_budgeted(schema, UNBOUNDED) == "to?: {  # Recipient.\n  email?: str\n}"


def _described(length: int) -> dict[str, JsonValue]:
    return _args({"q": {"type": "string", "description": "d" * length, "default": "x"}})


def _described_nest() -> dict[str, JsonValue]:
    leaf: dict[str, JsonValue] = {"type": "string", "description": "D."}
    c: dict[str, JsonValue] = {"type": "object", "description": "C.", "properties": {"d": leaf}}
    b: dict[str, JsonValue] = {"type": "object", "description": "B.", "properties": {"c": c}}
    a: dict[str, JsonValue] = {"type": "object", "description": "A.", "properties": {"b": b}}
    return _args({"x": {"type": "string", "description": "X."}, "a": a})


@pytest.mark.unit
class TestArgsBudget:
    def test_a_render_that_exactly_fits_keeps_whole_descriptions(self) -> None:
        full = f'q?: str  # {"d" * 200} [default: "x"]'
        assert render_args_budgeted(_described(200), len(full)) == full

    def test_descriptions_clip_to_160_first(self) -> None:
        clipped = f'q?: str  # {clip_text("d" * 200, 160)} [default: "x"]'
        assert render_args_budgeted(_described(200), len(clipped)) == clipped

    def test_then_to_60(self) -> None:
        clipped = f'q?: str  # {clip_text("d" * 200, 60)} [default: "x"]'
        assert render_args_budgeted(_described(200), len(clipped)) == clipped

    def test_then_descriptions_go_but_constraints_stay(self) -> None:
        bare = 'q?: str  # [default: "x"]'
        assert render_args_budgeted(_described(200), len(bare)) == bare

    def test_a_description_under_a_cap_is_never_marked_clipped(self) -> None:
        assert (
            render_args_budgeted(_described(10), UNBOUNDED)
            == f'q?: str  # {"d" * 10} [default: "x"]'
        )

    def test_the_last_description_tier_drops_nested_descriptions_too(self) -> None:
        no_descriptions = "x?: str\na?: {\n  b?: {\n    c?: {\n      d?: str\n    }\n  }\n}"
        assert render_args_budgeted(_described_nest(), len(no_descriptions)) == no_descriptions

    def test_depth_prunes_only_after_descriptions_are_gone(self) -> None:
        pruned = "x?: str\na?: {\n  b?: {\n    c?: obj\n  }\n}"
        assert render_args_budgeted(_described_nest(), len(pruned)) == (
            f"{pruned}\n(nested fields omitted for size)"
        )

    def test_each_prune_level_is_tried_in_turn(self) -> None:
        assert render_args_budgeted(_nested(4), len("a?: {\n  b?: obj\n}")) == (
            "a?: {\n  b?: obj\n}\n(nested fields omitted for size)"
        )
        assert render_args_budgeted(_nested(4), len("a?: obj")) == (
            "a?: obj\n(nested fields omitted for size)"
        )

    def test_nothing_fitting_clips_the_shallowest_render_without_descriptions(self) -> None:
        assert render_args_budgeted(_described_nest(), 14) == clip_text("x?: str\na?: obj", 14)


_SHAPES: dict[str, JsonValue] = {
    "type": "object",
    "required": ["a"],
    "properties": {
        "a": {
            "type": "array",
            "items": {"type": "object", "properties": {"b": {"type": "string"}}},
        },
        "m": {"type": "object", "additionalProperties": {"type": "integer"}},
    },
}


@pytest.mark.unit
class TestPruneToLevels:
    @pytest.mark.parametrize(
        ("levels", "expected"),
        [
            (0, {"type": "object", "required": ["a"], "properties": "..."}),
            (
                1,
                {
                    "type": "object",
                    "required": ["a"],
                    "properties": {
                        "a": {"type": "array", "items": "..."},
                        "m": {"type": "object", "additionalProperties": "..."},
                    },
                },
            ),
            (
                2,
                {
                    "type": "object",
                    "required": ["a"],
                    "properties": {
                        "a": {"type": "array", "items": {"type": "object", "properties": "..."}},
                        "m": {"type": "object", "additionalProperties": {"type": "integer"}},
                    },
                },
            ),
            (3, _SHAPES),
        ],
    )
    def test_each_level_keeps_exactly_that_much_nesting(
        self, levels: int, expected: dict[str, JsonValue]
    ) -> None:
        assert schema_notation._prune_to_levels(_SHAPES, levels) == expected

    def test_union_variants_are_pruned_at_the_unions_own_level(self) -> None:
        union: dict[str, JsonValue] = {
            "anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}}]
        }
        assert schema_notation._prune_to_levels(union, 0) == {
            "anyOf": [{"type": "object", "properties": "..."}]
        }
