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
        per_key = schema["properties"]["per_key"]
        # The keys are data and never stored — but the value shape is: a map is
        # modeled as additionalProperties, not as an opaque object.
        assert "properties" not in per_key
        assert per_key["additionalProperties"]["properties"]["count"] == {"type": "integer"}

    @pytest.mark.parametrize(
        "leaky_key",
        [
            "user@example.com",
            "4155551234567",
            "a3f1c2d4-9b8e-4f01-aaaa-bbbbccccdddd",
            "x" * 70,
            # A user-authored label. The denylist this replaced matched only
            # emails, digit runs, UUIDs and overlong strings, so a Notion
            # property or a Sheets tab name became a schema property in the
            # tool's GLOBAL record — rendered back to every other user of that
            # tool through get_tool_schema.
            "Sarah Chen - comp review",
            "Q3 spend / EMEA",
            "客戶名單",
        ],
        ids=["email", "digits", "uuid", "overlong", "person_label", "path_label", "non_ascii"],
    )
    async def test_a_value_looking_key_collapses_its_dict_to_a_map(self, leaky_key: str) -> None:
        # The wide-dict threshold alone would miss a small dict keyed by data;
        # the key pattern guard is what keeps PII out of schema property names.
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("T", {"per_user": {leaky_key: {"n": 1}}}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert leaky_key not in str(schema)
        per_user = schema["properties"]["per_user"]
        assert "properties" not in per_user
        assert per_user["additionalProperties"]["properties"]["n"] == {"type": "integer"}

    async def test_identifier_shaped_data_keys_over_one_repeated_structure_are_a_map(self) -> None:
        """The spelling guard cannot catch {"Engineering": {...}, "Marketing": {...}}
        — single-token labels are identifier-shaped. What gives the map away is
        every value sharing one structured shape; a record's fields differ."""
        repo = _repo()
        by_department = {
            "Engineering": {"headcount": 12, "open_roles": 3},
            "Marketing": {"headcount": 5, "open_roles": 1},
        }
        with patch(REPO, repo):
            await record_observed_shape("T", {"by_department": by_department}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert "Engineering" not in str(schema)
        value_shape = schema["properties"]["by_department"]["additionalProperties"]
        assert set(value_shape["properties"]) == {"headcount", "open_roles"}

    async def test_a_record_of_differing_field_shapes_keeps_its_fields(self) -> None:
        """The homogeneity signal must not collapse real records: any variation
        between value shapes — or any scalar field — is record evidence."""
        repo = _repo()
        response = {
            "user": {"id": "u1", "name": "x"},
            "team": {"id": "t1"},
            "ok": True,
        }
        with patch(REPO, repo):
            await record_observed_shape("T", response, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert set(schema["properties"]) == {"user", "team", "ok"}

    async def test_a_stored_map_shape_round_trips_through_the_next_merge(self) -> None:
        """additionalProperties must survive re-merging: the stored form re-enters
        genson's dialect, unions with the new observation's value shape, and
        comes back out as additionalProperties — never as literal properties."""
        stored = {
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
        }
        repo = _repo(existing_schema=stored)
        with patch(REPO, repo):
            await record_observed_shape(
                "T", {"per_user": {"bob@x.com": {"n": 2, "flag": True}}}, scope=SCOPE
            )
        (_, _, schema), _ = repo.record.await_args
        assert "bob@x.com" not in str(schema)
        per_user = schema["properties"]["per_user"]
        assert "properties" not in per_user
        assert set(per_user["additionalProperties"]["properties"]) == {"n", "flag"}

    @pytest.mark.parametrize(
        "field_name",
        ["message_id", "threadId", "content-type", "data.items", "$ref", "_internal"],
    )
    async def test_a_real_provider_field_name_still_becomes_a_property(
        self, field_name: str
    ) -> None:
        """The allowlist must not collapse the shapes the feature exists to learn:
        provider field names are identifier-shaped in every casing convention."""
        repo = _repo()
        with patch(REPO, repo):
            await record_observed_shape("T", {"record": {field_name: "v"}}, scope=SCOPE)
        (_, _, schema), _ = repo.record.await_args
        assert field_name in schema["properties"]["record"]["properties"]

    async def test_an_oversized_schema_keeps_the_stored_one(self) -> None:
        repo = _repo()
        # Per-section field names differ so this stays a (huge) record — a
        # repeated shape would rightly collapse to a small map schema instead.
        wide = {f"section_{n}": {f"field_{n}_{m}": "x" for m in range(20)} for n in range(400)}
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
