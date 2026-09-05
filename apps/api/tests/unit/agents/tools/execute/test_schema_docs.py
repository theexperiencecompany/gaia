"""render_tool_doc — the discovery contract: compact, budgeted, never invented."""

from unittest.mock import MagicMock

from pydantic import BaseModel, Field
import pytest

from app.agents.tools.execute.schema_docs import (
    render_compact_type,
    render_compact_type_budgeted,
    render_tool_doc,
)
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
        assert '"..."' in doc  # args pruned visibly, not clipped mid-JSON

    def test_compact_type_notation_core_shapes(self) -> None:
        schema = {
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
        rendered = render_compact_type(schema)
        assert rendered == (
            '{id:str, count:int, tags?:str[], status?:"open"|"closed", parent?:null|str, meta?:obj}'
        )

    def test_compact_type_renders_a_map_as_an_index_signature(self) -> None:
        """Observed shapes store data-keyed maps as additionalProperties; the
        notation must show the value shape, not degrade the map to bare obj."""
        schema = {
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

    def test_compact_type_union_array_items_are_grouped(self) -> None:
        schema = {
            "type": "array",
            "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        }
        # Without grouping, {a}|{b}[] misreads as a union with an array arm.
        assert render_compact_type(schema) == "(int|str)[]"

    def test_budgeted_compact_type_depth_collapses_when_oversized(self) -> None:
        rendered = render_compact_type_budgeted(_deep_response_schema(), 800)
        assert len(rendered.splitlines()[0]) <= 800
        assert "obj" in rendered  # collapsed depth is visible as bare obj
        assert "omitted for size" in rendered

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
