from unittest.mock import MagicMock

from mcp.types import Tool
from pydantic import BaseModel
import pytest

from app.services.mcp.langchain_adapter import SanitizingLangChainAdapter


def _args_schema(input_schema: dict[str, object]) -> type[BaseModel]:
    tool = SanitizingLangChainAdapter()._convert_tool(
        Tool(name="t", description="d", inputSchema=input_schema), MagicMock()
    )
    assert tool is not None
    assert isinstance(tool.args_schema, type)
    return tool.args_schema


@pytest.mark.regression
class TestAToolSchemaWithBooleanSubschemas:
    def test_a_true_items_schema_still_yields_a_usable_model(self) -> None:
        model = _args_schema(
            {
                "type": "object",
                "properties": {"tags": {"type": "array", "items": True}},
                "required": ["tags"],
            }
        )

        assert model(tags=["a", 1]).model_dump() == {"tags": ["a", 1]}

    def test_a_boolean_property_schema_still_yields_a_usable_model(self) -> None:
        model = _args_schema(
            {
                "type": "object",
                "properties": {"anything": True, "name": {"type": "string"}},
                "required": ["name"],
            }
        )

        assert model(name="n", anything={"x": 1}).model_dump() == {
            "anything": {"x": 1},
            "name": "n",
        }

    def test_boolean_combinator_members_still_yield_a_usable_model(self) -> None:
        model = _args_schema(
            {
                "type": "object",
                "properties": {"value": {"anyOf": [True, {"type": "string"}]}},
            }
        )

        assert model(value="v").model_dump() == {"value": "v"}

    def test_a_boolean_additional_properties_keyword_is_left_alone(self) -> None:
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        }

        fixed = SanitizingLangChainAdapter().fix_schema(schema)

        assert fixed["additionalProperties"] is False
