"""Observed-shape learning — structure in, structure stored, values never."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import tool_shape_service
from app.services.tool_shape_service import record_observed_shape

REPO = "app.services.tool_shape_service.tool_shapes_repository"
SCOPE = "global"


def _repo(existing_schema: dict | None = None) -> MagicMock:
    repo = MagicMock()
    doc = None
    if existing_schema is not None:
        doc = MagicMock()
        doc.output_schema = existing_schema
    repo.get_shape = AsyncMock(return_value=doc)
    repo.record = AsyncMock()
    return repo


@pytest.mark.unit
class TestRecordObservedShape:
    async def test_structure_is_stored_and_values_are_not(self) -> None:
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape(
                "GMAIL_FETCH_EMAILS",
                {"data": {"messages": [{"id": "msg_8842", "subject": "salary review"}]}},
                scope=SCOPE,
            )
        (scope, tool_name, schema), _ = repo.record.await_args
        assert (scope, tool_name) == (SCOPE, "GMAIL_FETCH_EMAILS")
        items = schema["properties"]["data"]["properties"]["messages"]["items"]
        assert items["properties"]["id"] == {"type": "string"}
        # No value from the real response may reach the store.
        assert "msg_8842" not in str(schema)
        assert "salary review" not in str(schema)

    async def test_the_record_lands_in_the_resolved_scope(self) -> None:
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("MY_CRM_LOOKUP", {"hit": True}, scope="mcp:crm-123")
        repo.get_shape.assert_awaited_once_with("mcp:crm-123", "MY_CRM_LOOKUP")
        (scope, _, _), _ = repo.record.await_args
        assert scope == "mcp:crm-123"

    async def test_new_observation_merges_with_the_stored_schema(self) -> None:
        stored = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        }
        repo = _repo(existing_schema=stored)
        with patch(REPO, repo):
            await record_observed_shape("T", {"b": 1}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert set(schema["properties"]) == {"a", "b"}
        # "a" was absent this time, so it is no longer required.
        assert schema.get("required", []) == []

    async def test_arrays_are_sampled_not_walked_wholesale(self) -> None:
        repo = _repo()
        # A field appearing only past the sample window must not reach the
        # schema — that is what proves the array was sampled, not walked.
        items: list[dict] = [{"i": n} for n in range(400)]
        items.append({"i": 400, "beyond_sample": "x"})
        with patch(REPO, repo):
            await record_observed_shape("T", {"items": items}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        item_props = schema["properties"]["items"]["items"]["properties"]
        assert "i" in item_props
        assert "beyond_sample" not in item_props

    async def test_a_wide_dict_is_treated_as_a_map_not_a_record(self) -> None:
        repo = _repo()
        wide = {f"k{n}": {"count": n} for n in range(40)}
        with patch(REPO, repo):
            await record_observed_shape("T", {"per_key": wide}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert "k0" not in str(schema)
        assert schema["properties"]["per_key"] == {"type": "object"}

    @pytest.mark.parametrize(
        "leaky_key",
        [
            "user@example.com",
            "4155551234567",
            "a3f1c2d4-9b8e-4f01-aaaa-bbbbccccdddd",
            "x" * 70,
        ],
        ids=["email", "digits", "uuid", "overlong"],
    )
    async def test_a_value_looking_key_collapses_its_dict_to_a_map(self, leaky_key: str) -> None:
        # The wide-dict threshold alone would miss a small dict keyed by data;
        # the key pattern guard is what keeps PII out of schema property names.
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("T", {"per_user": {leaky_key: {"n": 1}}}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert leaky_key not in str(schema)
        assert schema["properties"]["per_user"] == {"type": "object"}

    async def test_an_oversized_schema_keeps_the_stored_one(self) -> None:
        repo = _repo()
        wide = {f"section_{n}": {f"field_{m}": "x" for m in range(20)} for n in range(400)}
        with (
            patch(REPO, repo),
            patch.object(tool_shape_service, "TOOL_SHAPE_MAX_KEYS_PER_OBJECT", 10_000),
            patch.object(tool_shape_service, "TOOL_SHAPE_MAX_CHARS", 500),
        ):
            await record_observed_shape("T", wide, scope=SCOPE)
        repo.record.assert_not_awaited()

    async def test_a_non_dict_output_records_nothing(self) -> None:
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("T", "plain text result", scope=SCOPE)
        repo.get_shape.assert_not_awaited()
        repo.record.assert_not_awaited()

    async def test_non_json_scalars_become_string_typed_not_errors(self) -> None:
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("T", {"ts": datetime.now(UTC)}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert schema["properties"]["ts"] == {"type": "string"}
