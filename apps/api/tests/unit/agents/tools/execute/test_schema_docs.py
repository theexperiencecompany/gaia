"""render_tool_doc — the discovery contract: compact, capped, never invented."""

from unittest.mock import MagicMock

from pydantic import BaseModel, Field
import pytest

from app.agents.tools.execute.schema_docs import render_tool_doc
from app.constants.execute import RESPONSE_SCHEMA_MAX_CHARS, SCHEMA_DOC_MAX_CHARS


class _Args(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = 25


def _tool(
    name: str = "GMAIL_FETCH_EMAILS",
    description: str = "Fetch emails.",
    metadata: dict | None = None,
) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.args_schema = _Args
    tool.metadata = metadata
    return tool


@pytest.mark.unit
class TestRenderToolDoc:
    def test_doc_carries_name_description_and_args_schema(self) -> None:
        doc = render_tool_doc(_tool())
        assert "## GMAIL_FETCH_EMAILS" in doc
        assert "Fetch emails." in doc
        assert '"query"' in doc and '"max_results"' in doc
        assert 'tool_name="GMAIL_FETCH_EMAILS"' in doc

    def test_generator_noise_and_internal_params_are_stripped(self) -> None:
        class _WithInternal(BaseModel):
            query: str

        tool = _tool()
        schema = _WithInternal.model_json_schema()
        schema["properties"]["__runnable_config__"] = {"type": "string"}
        tool.args_schema = schema
        doc = render_tool_doc(tool)
        assert "__runnable_config__" not in doc
        assert '"title"' not in doc

    def test_returns_section_only_when_provider_supplies_one(self) -> None:
        without = render_tool_doc(_tool(metadata=None))
        assert "Returns:" not in without
        with_returns = render_tool_doc(
            _tool(metadata={"output_parameters": {"properties": {"id": {"type": "string"}}}})
        )
        assert "Returns:" in with_returns
        assert '"id"' in with_returns

    def test_large_response_schema_degrades_to_top_levels_not_wholesale(self) -> None:
        deep = {
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
        doc = render_tool_doc(_tool(metadata={"output_parameters": deep}))
        returns = doc.split("Returns:")[1]
        assert '"data"' in returns  # the top-level shape survives
        assert '"leaf"' not in returns  # deep detail is pruned, not injected
        assert '"..."' in returns  # truncation is visible to the model, not silent
        assert len(returns) <= RESPONSE_SCHEMA_MAX_CHARS + 200  # truncation-note allowance

    def test_unprunable_response_schema_floors_at_field_names(self) -> None:
        # Hundreds of top-level fields: no depth level fits, so the render
        # floors at a names-only listing instead of dropping Returns entirely.
        wide = {
            "type": "object",
            "properties": {
                f"field_{i}": {"type": "string", "description": "x" * 80} for i in range(400)
            },
        }
        doc = render_tool_doc(_tool(metadata={"output_parameters": wide}))
        returns = doc.split("Returns:")[1]
        assert '"fields"' in returns
        assert '"field_0"' in returns
        assert len(returns) <= RESPONSE_SCHEMA_MAX_CHARS + 200

    def test_huge_schema_is_capped(self) -> None:
        huge = {
            "type": "object",
            "properties": {
                f"field_{i}": {"type": "string", "description": "x" * 80} for i in range(400)
            },
        }
        tool = _tool(metadata={"output_parameters": huge})
        tool.args_schema = huge
        doc = render_tool_doc(tool)
        assert len(doc) <= SCHEMA_DOC_MAX_CHARS + 50  # clip marker allowance

    def test_huge_args_schema_never_starves_the_rest_of_the_doc(self) -> None:
        # Real case: GOOGLECALENDAR_EVENTS_LIST's args schema alone exceeded the
        # doc cap, clipping away Returns and the usage line mid-JSON.
        deep_args = {
            "type": "object",
            "properties": {
                f"arg_{i}": {
                    "type": "object",
                    "properties": {"nested": {"type": "string", "description": "z" * 200}},
                }
                for i in range(60)
            },
        }
        tool = _tool(metadata={"output_parameters": {"properties": {"id": {"type": "string"}}}})
        tool.args_schema = deep_args
        doc = render_tool_doc(tool)
        assert "Returns:" in doc and '"id"' in doc  # response shape survives
        assert 'tool_name="GMAIL_FETCH_EMAILS"' in doc  # usage line survives
        assert '"..."' in doc  # args pruned visibly, not clipped mid-JSON
