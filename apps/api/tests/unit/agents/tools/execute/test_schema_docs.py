"""render_tool_doc — the discovery contract: compact, budgeted, never invented."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from pydantic import BaseModel, Field, JsonValue
import pytest

from app.agents.tools.execute.schema_docs import _args_schema_of, render_tool_doc
from app.constants.execute import SCHEMA_DOC_MAX_CHARS


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
    def test_doc_carries_name_description_and_args(self) -> None:
        doc = render_tool_doc(_tool())
        assert "## GMAIL_FETCH_EMAILS" in doc
        assert "Fetch emails." in doc
        assert "query: str  # Search query" in doc
        assert "max_results?: int  # [default: 25]" in doc
        assert 'tool_name="GMAIL_FETCH_EMAILS"' in doc

    def test_internal_params_never_reach_the_doc(self) -> None:
        class _WithInternal(BaseModel):
            query: str

        tool = _tool()
        schema = _WithInternal.model_json_schema()
        schema["properties"]["__runnable_config__"] = {"type": "string"}
        tool.args_schema = schema
        assert "__runnable_config__" not in render_tool_doc(tool)

    def test_returns_never_render_in_discovery_docs(self) -> None:
        # Shapes are explored on demand (get_tool_schema / gaia.schema), never
        # paid for in every discovery doc - even when the provider supplies one.
        with_schema = _tool(metadata={"output_parameters": _deep_response_schema()})
        assert "Returns" not in render_tool_doc(with_schema)
        assert "Returns" not in render_tool_doc(_tool(metadata=None))

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
        tool = _tool()
        tool.args_schema = deep_args
        doc = render_tool_doc(tool)
        assert 'tool_name="GMAIL_FETCH_EMAILS"' in doc  # usage line survives
        assert "  nested?: str\n" in doc  # descriptions went, structure stayed
        assert "z" * 10 not in doc

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


@pytest.mark.unit
class TestRenderToolDocLayout:
    def test_a_tool_with_no_description_or_schema_still_documents_its_call(self) -> None:
        tool = _tool(name="PING", description="")
        tool.args_schema = None
        assert render_tool_doc(tool).split("\n") == [
            "## PING",
            "Args for execute(tool_name=..., data={...}), ? = optional:",
            "obj",
            'Run it with: execute(task_description="...", tool_name="PING", data={...})',
        ]

    def test_a_documented_tool_reads_header_args_then_usage(self) -> None:
        assert render_tool_doc(_tool()).split("\n") == [
            "## GMAIL_FETCH_EMAILS",
            "Fetch emails.",
            "Args for execute(tool_name=..., data={...}), ? = optional:",
            "query: str  # Search query",
            "max_results?: int  # [default: 25]",
            'Run it with: execute(task_description="...", '
            'tool_name="GMAIL_FETCH_EMAILS", data={...})',
        ]

    def test_a_schema_carrying_a_python_value_still_renders(self) -> None:
        """Python-built dict schemas can carry non-JSON defaults; a doc must render them, not crash retrieval."""
        when = datetime(2026, 1, 1, tzinfo=UTC)
        tool = _tool()
        tool.args_schema = {
            "type": "object",
            "properties": {"at": {"type": "string", "default": when}},
        }
        assert 'at?: str  # [default: "2026-01-01 00:00:00+00:00"]' in render_tool_doc(tool)


@pytest.mark.unit
class TestArgsSchemaOf:
    def test_internal_params_leave_required_and_titles_leave_nested_variants(self) -> None:
        tool = _tool()
        tool.args_schema = {
            "type": "object",
            "title": "Args",
            "properties": {
                "q": {"anyOf": [{"type": "string", "title": "Q"}]},
                "__runnable_config__": {"type": "object"},
            },
            "required": ["q", "__runnable_config__"],
        }
        assert _args_schema_of(tool) == {
            "type": "object",
            "properties": {"q": {"anyOf": [{"type": "string"}]}},
            "required": ["q"],
        }

    def test_a_tool_without_a_schema_takes_no_args(self) -> None:
        tool = _tool()
        tool.args_schema = None
        assert _args_schema_of(tool) == {"type": "object", "properties": {}}


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
    @pytest.mark.regression
    def test_types_required_and_constraints_survive_a_schema_over_budget(self) -> None:
        """Regression: an over-budget args schema collapsed to bare field names, dropping every type, required marker and constraint."""
        tool = _tool()
        tool.args_schema = _calendar_like_args()
        doc = render_tool_doc(tool)
        assert "start_datetime: str" in doc
        assert "format: date-time" in doc
        assert 'visibility?: "default"|"public"|"private"' in doc
        assert "option_0?: bool" in doc
        assert '"fields":' not in doc

    @pytest.mark.regression
    def test_a_nested_model_renders_its_fields_not_a_ref(self) -> None:
        """Regression: a $ref'd nested model (GMAIL_SEND_EMAIL attachments) reached the model as a $defs pointer to chase."""
        tool = _tool()
        tool.args_schema = _SendArgs
        doc = render_tool_doc(tool)
        assert "attachments?: null|{\n  url: str  # A fetchable URL to the file.\n}[]" in doc
        assert "$ref" not in doc
