"""render_tool_doc — the doc discovery and get_tool_schema share: compact, budgeted, never invented."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, JsonValue
import pytest

from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.schema_docs import render_tool_doc
from app.agents.tools.execute.tool_info import tool_contract
from app.constants.execute import ARGS_SCHEMA_MAX_CHARS, RETURNS_INLINE_MAX_CHARS
from app.db.repositories.tool_shapes import tool_shapes_repository
from app.models.tool_shape_models import ToolOutputShapeDocument


class _Args(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = 25


USAGE = 'Run it with: execute(task_description="...", tool_name="GMAIL_FETCH_EMAILS", data={...})'
ARGS_HEADER = "Args for execute(tool_name=..., data={...}), ? = optional:"
UNDOCUMENTED = (
    "Return shape: not documented yet; it is learned from real calls. "
    "Inspect the first response before consuming fields."
)


def _tool(
    args_schema: type[BaseModel] | dict[str, Any] | None = _Args,
    output: dict[str, JsonValue] | None = None,
    name: str = "GMAIL_FETCH_EMAILS",
    description: str = "Fetch emails.",
) -> StructuredTool:
    tool = StructuredTool.from_function(
        func=lambda **kwargs: None,
        name=name,
        description=description,
        metadata={"output_parameters": output} if output else None,
    )
    tool.args_schema = args_schema
    return tool


async def _doc(
    tool: StructuredTool,
    budget: int = RETURNS_INLINE_MAX_CHARS,
    observed: ToolOutputShapeDocument | None = None,
) -> str:
    with patch.object(tool_shapes_repository, "get_shape", new=AsyncMock(return_value=observed)):
        info = await tool_contract(ResolvedTool(tool.name, tool, True))
    return render_tool_doc(info, budget)


def _observed(schema: dict[str, JsonValue], calls: int) -> ToolOutputShapeDocument:
    return ToolOutputShapeDocument(
        tool_name="GMAIL_FETCH_EMAILS",
        output_schema=schema,
        call_count=calls,
        last_seen=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _wide_output(fields: int) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "properties": {
                    f"field_{i}": {"type": "object", "properties": {"leaf": {"type": "string"}}}
                    for i in range(fields)
                },
            }
        },
    }


@pytest.mark.unit
class TestRenderToolDoc:
    async def test_a_documented_tool_reads_header_args_returns_then_usage(self) -> None:
        output: dict[str, JsonValue] = {
            "type": "object",
            "properties": {"messages": {"type": "array", "items": {"type": "string"}}},
            "required": ["messages"],
        }
        assert (await _doc(_tool(output=output))).split("\n") == [
            "## GMAIL_FETCH_EMAILS",
            "Fetch emails.",
            ARGS_HEADER,
            "query: str  # Search query",
            "max_results?: int  # [default: 25]",
            "Returns: {messages:str[]}",
            USAGE,
        ]

    async def test_a_tool_with_no_description_schema_or_shape_still_documents_its_call(
        self,
    ) -> None:
        assert (await _doc(_tool(args_schema=None, description=""))).split("\n") == [
            "## GMAIL_FETCH_EMAILS",
            ARGS_HEADER,
            "obj",
            UNDOCUMENTED,
            USAGE,
        ]

    async def test_an_observed_shape_renders_with_its_confidence(self) -> None:
        observed = _observed({"type": "object", "properties": {"ok": {"type": "boolean"}}}, 17)
        doc = await _doc(_tool(), observed=observed)
        assert "Returns: {ok?:bool}\n(shape observed from 17 real calls)\n" in doc

    async def test_the_provider_shape_wins_and_needs_no_confidence_note(self) -> None:
        observed = _observed({"type": "object", "properties": {"ok": {"type": "boolean"}}}, 17)
        output: dict[str, JsonValue] = {"type": "object", "properties": {"id": {"type": "string"}}}
        doc = await _doc(_tool(output=output), observed=observed)
        assert "Returns: {id?:str}\n" + USAGE in doc
        assert "observed from" not in doc

    async def test_a_return_shape_over_budget_collapses_by_depth(self) -> None:
        doc = await _doc(_tool(output=_wide_output(50)))
        returns = doc.split("Returns: ")[1].split("\n")
        assert len(returns[0]) <= RETURNS_INLINE_MAX_CHARS
        assert "field_0?:obj" in returns[0]
        assert returns[1] == "(deeper fields omitted for size; the real data has them)"
        assert returns[2] == USAGE

    async def test_a_larger_budget_keeps_more_of_the_shape(self) -> None:
        doc = await _doc(_tool(output=_wide_output(50)), budget=4000)
        assert "field_0?:{leaf?:str}" in doc

    async def test_internal_params_never_reach_the_doc(self) -> None:
        class _WithInternal(BaseModel):
            query: str

        schema = _WithInternal.model_json_schema()
        schema["properties"]["__runnable_config__"] = {"type": "string"}
        assert "__runnable_config__" not in await _doc(_tool(args_schema=schema))

    async def test_huge_args_schema_never_starves_the_rest_of_the_doc(self) -> None:
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
        doc = await _doc(_tool(args_schema=deep_args))
        assert doc.endswith(USAGE)
        assert "  nested?: str\n" in doc  # descriptions went, structure stayed
        assert "z" * 10 not in doc

    async def test_every_section_is_budgeted(self) -> None:
        huge: dict[str, JsonValue] = {
            "type": "object",
            "properties": {
                f"field_{i}": {"type": "string", "description": "x" * 80} for i in range(400)
            },
        }
        doc = await _doc(_tool(args_schema=huge, output=huge, description="d" * 5000))
        fixed_lines = len(USAGE) + len(ARGS_HEADER) + len("## GMAIL_FETCH_EMAILS") + 200
        assert len(doc) <= 600 + ARGS_SCHEMA_MAX_CHARS + RETURNS_INLINE_MAX_CHARS + fixed_lines

    async def test_a_schema_carrying_a_python_value_still_renders(self) -> None:
        """Python-built dict schemas can carry non-JSON defaults; a doc must render them, not crash retrieval."""
        schema = {
            "type": "object",
            "properties": {"at": {"type": "string", "default": datetime(2026, 1, 1, tzinfo=UTC)}},
        }
        doc = await _doc(_tool(args_schema=schema))
        assert 'at?: str  # [default: "2026-01-01 00:00:00+00:00"]' in doc


def _calendar_like_args() -> dict[str, JsonValue]:
    """Shaped like GOOGLECALENDAR_CREATE_EVENT: verbose descriptions and examples push the JSON past budget."""
    properties: dict[str, JsonValue] = {
        f"option_{i}": {
            "type": "boolean",
            "description": "An option that changes how the event is created. " * 3,
            "examples": [True, False],
        }
        for i in range(20)
    }
    properties["start_datetime"] = {
        "type": "string",
        "format": "date-time",
        "description": "Event start in ISO 8601.",
        "examples": ["2026-01-01T10:00:00"],
    }
    properties["visibility"] = {
        "type": "string",
        "enum": ["default", "public", "private"],
        "default": "default",
    }
    return {"type": "object", "properties": properties, "required": ["start_datetime"]}


class _Attachment(BaseModel):
    url: str = Field(description="A fetchable URL to the file.")


class _SendArgs(BaseModel):
    subject: str
    attachments: list[_Attachment] | None = None


@pytest.mark.unit
class TestOversizedArgsKeepTheirContract:
    async def test_types_required_and_constraints_survive_a_schema_over_budget(self) -> None:
        """Regression: an over-budget args schema collapsed to bare field names, dropping every type, required marker and constraint."""
        doc = await _doc(_tool(args_schema=_calendar_like_args()))
        assert "start_datetime: str" in doc
        assert "format: date-time" in doc
        assert 'visibility?: "default"|"public"|"private"' in doc
        assert "option_0?: bool" in doc
        assert '"fields":' not in doc

    async def test_a_nested_model_renders_its_fields_not_a_ref(self) -> None:
        """Regression: a $ref'd nested model (GMAIL_SEND_EMAIL attachments) reached the model as a $defs pointer to chase."""
        doc = await _doc(_tool(args_schema=_SendArgs))
        assert "attachments?: null|{\n  url: str  # A fetchable URL to the file.\n}[]" in doc
        assert "$ref" not in doc
