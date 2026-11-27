"""without_size_caps takes maxLength/maxItems out of a JSON schema and nothing else."""

from pydantic import JsonValue
import pytest

from app.agents.llm.schema_caps import without_size_caps


@pytest.mark.parametrize(
    ("schema", "stripped"),
    [
        ({"type": "string", "maxLength": 5, "minLength": 1}, {"type": "string", "minLength": 1}),
        (
            {"type": "array", "maxItems": 2, "minItems": 1, "items": {"maxLength": 3}},
            {"type": "array", "minItems": 1, "items": {}},
        ),
        (
            {"anyOf": [{"type": "string", "maxLength": 5}, {"type": "null"}]},
            {"anyOf": [{"type": "string"}, {"type": "null"}]},
        ),
        (
            {"$defs": {"Item": {"properties": {"name": {"maxLength": 9}}, "maxItems": 4}}},
            {"$defs": {"Item": {"properties": {"name": {}}}}},
        ),
        (
            {"definitions": {"maxItems": {"type": "string", "maxLength": 9}}},
            {"definitions": {"maxItems": {"type": "string"}}},
        ),
        (
            {"patternProperties": {"maxLength": {"type": "array", "maxItems": 9}}},
            {"patternProperties": {"maxLength": {"type": "array"}}},
        ),
    ],
)
def test_a_cap_is_removed_wherever_a_schema_sits(schema: JsonValue, stripped: JsonValue) -> None:
    assert without_size_caps(schema) == stripped


@pytest.mark.parametrize("keyword", ["enum", "const", "default", "examples"])
def test_data_that_looks_like_a_cap_is_left_alone(keyword: str) -> None:
    """A default or an enum member is the tool's data, whatever its keys are called."""
    schema: JsonValue = {keyword: [{"maxLength": 1, "maxItems": 2}], "maxLength": 3}

    assert without_size_caps(schema) == {keyword: [{"maxLength": 1, "maxItems": 2}]}


def test_an_argument_named_like_a_cap_keeps_its_place_and_loses_its_own_cap() -> None:
    schema: JsonValue = {
        "properties": {
            "maxItems": {"type": "integer"},
            "maxLength": {"type": "string", "maxLength": 4},
        }
    }

    assert without_size_caps(schema) == {
        "properties": {"maxItems": {"type": "integer"}, "maxLength": {"type": "string"}}
    }


def test_a_keyword_holding_no_schema_map_is_passed_through() -> None:
    assert without_size_caps({"properties": True, "required": ["a"]}) == {
        "properties": True,
        "required": ["a"],
    }


@pytest.mark.parametrize("value", [None, True, 3, "maxLength"])
def test_a_bare_value_is_returned_as_it_is(value: JsonValue) -> None:
    assert without_size_caps(value) == value


def test_the_schema_passed_in_is_not_changed() -> None:
    schema: JsonValue = {"properties": {"name": {"maxLength": 9}}}

    without_size_caps(schema)

    assert schema == {"properties": {"name": {"maxLength": 9}}}
