"""render_tool_doc — the discovery contract: compact, budgeted, never invented."""

from unittest.mock import MagicMock

from pydantic import BaseModel, Field
import pytest

from app.agents.tools.execute.schema_docs import render_tool_doc
from app.constants.execute import (
    RESPONSE_SCHEMA_INLINE_MAX_CHARS,
    SANDBOX_TOOL_DOCS_DIR,
    SCHEMA_DOC_MAX_CHARS,
)


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


def _deep_response_schema() -> dict:
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

    def test_returns_section_absent_when_nothing_documents_the_shape(self) -> None:
        assert "Returns:" not in render_tool_doc(_tool(metadata=None))

    def test_small_provider_schema_renders_inline(self) -> None:
        doc = render_tool_doc(
            _tool(metadata={"output_parameters": {"properties": {"id": {"type": "string"}}}})
        )
        assert "Returns:" in doc
        assert '"id"' in doc

    def test_large_response_schema_becomes_a_pointer_not_inline_json(self) -> None:
        doc = render_tool_doc(_tool(metadata={"output_parameters": _deep_response_schema()}))
        returns_line = next(line for line in doc.splitlines() if line.startswith("Returns:"))
        # Top-level names still orient the model; the depth is one lookup away.
        assert "data" in returns_line
        assert 'gaia.schema("GMAIL_FETCH_EMAILS")' in returns_line
        assert f"{SANDBOX_TOOL_DOCS_DIR}/GMAIL_FETCH_EMAILS.json" in returns_line
        assert '"leaf"' not in doc  # the schema body itself is NOT injected
        assert len(returns_line) < RESPONSE_SCHEMA_INLINE_MAX_CHARS  # the pointer is cheap

    def test_observed_shape_fills_in_when_the_provider_documents_nothing(self) -> None:
        doc = render_tool_doc(
            _tool(metadata=None),
            observed_schema={"type": "object", "properties": {"messages": {"type": "array"}}},
        )
        assert "Returns:" in doc
        assert '"messages"' in doc

    def test_provider_schema_wins_over_observed(self) -> None:
        doc = render_tool_doc(
            _tool(metadata={"output_parameters": {"properties": {"prov": {"type": "string"}}}}),
            observed_schema={"properties": {"obs": {"type": "string"}}},
        )
        assert '"prov"' in doc
        assert '"obs"' not in doc

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
