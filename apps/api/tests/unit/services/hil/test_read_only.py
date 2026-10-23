"""Which tools a read-only run may call: metadata decides when it speaks, else every check must agree."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

from langchain_core.tools import BaseTool, StructuredTool
import pytest

from app.constants.hil import COMPOSIO_TAGS_METADATA_KEY
from app.models.hil_models import ToolReadOnlyVerdict
from app.services.hil.read_only import (
    _ReadOnlyJudgement,
    is_read_only,
    read_only_declaration,
    tool_shape_hash,
    voices_write_intent,
)
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY

from .conftest import make_tool

MODULE = "app.services.hil.read_only"


class TestReadOnlyDeclaration:
    def test_an_mcp_read_only_hint_declares_it(self) -> None:
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"readOnlyHint": True}})
        assert read_only_declaration(tool) is True

    def test_a_read_only_hint_that_is_also_destructive_does_not(self) -> None:
        annotations = {"readOnlyHint": True, "destructiveHint": True}
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: annotations})
        assert read_only_declaration(tool) is False

    @pytest.mark.parametrize("annotations", [{"readOnlyHint": False}, {"readOnlyHint": "true"}])
    def test_a_read_only_hint_that_is_not_true_is_a_no(
        self, annotations: dict[str, object]
    ) -> None:
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: annotations})
        assert read_only_declaration(tool) is False

    @pytest.mark.parametrize("annotations", [{}, {"title": "x"}, {"destructiveHint": False}])
    def test_annotations_without_a_read_only_hint_are_silent(
        self, annotations: dict[str, object]
    ) -> None:
        tool = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: annotations})
        assert read_only_declaration(tool) is None

    def test_a_composio_read_only_tag_declares_it(self) -> None:
        tags = ["important", "openWorldHint", "readOnlyHint"]
        assert read_only_declaration(make_tool(metadata={COMPOSIO_TAGS_METADATA_KEY: tags}))

    @pytest.mark.parametrize("write_tag", ["destructiveHint", "updateHint", "createHint"])
    def test_a_composio_write_tag_beats_a_read_only_tag(self, write_tag: str) -> None:
        tags = ["readOnlyHint", write_tag]
        tool = make_tool(metadata={COMPOSIO_TAGS_METADATA_KEY: tags})
        assert read_only_declaration(tool) is False

    def test_a_composio_tool_tagged_without_read_only_is_a_no(self) -> None:
        tool = make_tool(metadata={COMPOSIO_TAGS_METADATA_KEY: ["important", "tasks"]})
        assert read_only_declaration(tool) is False

    @pytest.mark.parametrize("metadata", [None, {}, {COMPOSIO_TAGS_METADATA_KEY: "readOnlyHint"}])
    def test_no_metadata_is_silent(self, metadata: dict[str, object] | None) -> None:
        assert read_only_declaration(make_tool(metadata=metadata)) is None


class TestVoicesWriteIntent:
    @pytest.mark.parametrize(
        ("name", "description"),
        [
            ("list_open_tickets", "List open tickets."),
            ("getPage", "Fetch one page by id."),
            ("search-issues", "Search issues, open or closed, created this week."),
            ("verify-domain", "Check whether a domain resolves."),
            ("issues", ""),
        ],
    )
    def test_no_write_token_leaves_it_to_the_model(self, name: str, description: str) -> None:
        assert voices_write_intent(name, description) is False

    @pytest.mark.parametrize(
        ("name", "description"),
        [
            ("get_or_create", "Get a record."),
            ("run_query", "Query rows."),
            ("search_and_replace", "Search text."),
            ("export", "A report."),
            ("accept_invitation", "An invitation."),
            ("listRunsAndDeleteOld", "Runs."),
            ("list_archived_items", "Items."),
            ("fetch_digest", "Fetches a digest and sends it to the team."),
            ("get_status", "Gets the status, updating the cache when stale."),
        ],
    )
    def test_a_write_token_in_the_name_or_description_is_a_no(
        self, name: str, description: str
    ) -> None:
        assert voices_write_intent(name, description) is True


@dataclass
class _Verdicts:
    """Stands in for the Mongo verdict cache and the helper model."""

    cache: dict[str, ToolReadOnlyVerdict] = field(default_factory=dict)
    judge: AsyncMock = field(
        default_factory=lambda: AsyncMock(
            return_value=_ReadOnlyJudgement(has_side_effects=False, certain=True)
        )
    )

    async def find_verdict(self, tool_hash: str) -> ToolReadOnlyVerdict | None:
        return self.cache.get(tool_hash)

    async def upsert_verdict(self, verdict: ToolReadOnlyVerdict) -> None:
        self.cache[verdict.tool_hash] = verdict


@pytest.fixture
def verdicts() -> Iterator[_Verdicts]:
    state = _Verdicts()
    with (
        patch(f"{MODULE}.tool_read_only_verdict_repository", state),
        patch(f"{MODULE}.ainvoke_structured", state.judge),
    ):
        yield state


def _reading_tool(description: str = "List open tickets.") -> BaseTool:
    return make_tool(name="list_open_tickets", description=description)


class TestIsReadOnly:
    async def test_metadata_decides_without_asking_the_model(self, verdicts: _Verdicts) -> None:
        denied = make_tool(
            name="list_open_tickets",
            description="List open tickets.",
            metadata={MCP_ANNOTATIONS_METADATA_KEY: {"readOnlyHint": False}},
        )
        allowed = make_tool(metadata={MCP_ANNOTATIONS_METADATA_KEY: {"readOnlyHint": True}})

        assert (await is_read_only(denied), await is_read_only(allowed)) == (False, True)
        verdicts.judge.assert_not_awaited()

    @pytest.mark.parametrize("name", ["get_or_create", "run_query", "search_and_replace", "export"])
    async def test_a_silent_tool_voicing_a_write_never_reaches_the_model(
        self, verdicts: _Verdicts, name: str
    ) -> None:
        assert await is_read_only(make_tool(name=name, description="A record.")) is False
        verdicts.judge.assert_not_awaited()

    async def test_a_name_with_no_read_verb_is_decided_by_the_model(
        self, verdicts: _Verdicts
    ) -> None:
        tool = make_tool(name="issues", description="Issues assigned to the user.")

        assert await is_read_only(tool) is True
        verdicts.judge.return_value = _ReadOnlyJudgement(has_side_effects=True, certain=True)
        assert await is_read_only(make_tool(name="verify-domain", description="A domain.")) is False

    async def test_the_model_sees_the_full_input_schema(self, verdicts: _Verdicts) -> None:
        tool = StructuredTool.from_function(
            func=lambda notes: None,
            name="lookup_contact",
            description="A contact.",
            args_schema={
                "type": "object",
                "properties": {"notes": {"type": "string", "description": "n" * 5000}},
            },
        )

        await is_read_only(tool)

        assert "n" * 5000 in verdicts.judge.await_args.args[1]

    async def test_a_silent_reading_tool_is_read_only_when_the_model_agrees(
        self, verdicts: _Verdicts
    ) -> None:
        tool = _reading_tool()

        assert await is_read_only(tool) is True
        assert verdicts.cache[tool_shape_hash(tool)].read_only is True

    @pytest.mark.parametrize(
        "judgement",
        [
            _ReadOnlyJudgement(has_side_effects=True, certain=True),
            _ReadOnlyJudgement(has_side_effects=False, certain=False),
            _ReadOnlyJudgement(has_side_effects=True, certain=False),
        ],
    )
    async def test_a_model_that_disagrees_or_doubts_is_a_no(
        self, verdicts: _Verdicts, judgement: _ReadOnlyJudgement
    ) -> None:
        verdicts.judge.return_value = judgement

        assert await is_read_only(_reading_tool()) is False

    async def test_a_tool_is_classified_once_per_shape(self, verdicts: _Verdicts) -> None:
        tool = _reading_tool()

        assert [await is_read_only(tool) for _ in range(3)] == [True, True, True]
        assert verdicts.judge.await_count == 1

    async def test_a_changed_description_is_classified_again(self, verdicts: _Verdicts) -> None:
        await is_read_only(_reading_tool())
        verdicts.judge.return_value = _ReadOnlyJudgement(has_side_effects=True, certain=True)

        assert await is_read_only(_reading_tool("List open tickets and their owners.")) is False
        assert verdicts.judge.await_count == 2

    async def test_a_failed_classification_raises_and_caches_nothing(
        self, verdicts: _Verdicts
    ) -> None:
        verdicts.judge.side_effect = TimeoutError("helper lane down")

        with pytest.raises(TimeoutError):
            await is_read_only(_reading_tool())
        assert verdicts.cache == {}

    async def test_no_tool_is_a_no(self, verdicts: _Verdicts) -> None:
        assert await is_read_only(None) is False
