"""Attacks on HIL preferences (app/services/hil/preferences.py).

Preferences decide *which* tools are gated, so a lost or misapplied write is a gate that
silently stops asking. Three things carry the weight:

* **The cache must not outlive a write.** A stale read after an update means the user's
  new setting does not take effect until the TTL expires.
* **A per-tool write must touch only that tool.** Every switch on the integration panel
  fires its own request, so a read-modify-write of the whole map loses whichever ones
  landed in between.
* **A dotted MCP tool name must stay a flat key.** Mongo splits dotted ``$set`` paths into
  subdocuments, which the read path would then never find.

The Mongo collection is mocked, so the assertions are on the *query documents* the module
builds — that is where all three of those bugs live.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.models.hil_models import HILPreferences
from app.services.hil.preferences import (
    get_hil_preferences,
    set_tool_override,
    update_hil_preferences,
)

from .conftest import USER_ID

MODULE = "app.services.hil.preferences"


@pytest.fixture
def store():
    """Mongo + the Redis read-through cache, with an empty-cache / no-prefs default."""
    with (
        patch(f"{MODULE}.users_collection") as users,
        patch(f"{MODULE}.get_cache", new=AsyncMock(return_value=None)) as get_cache,
        patch(f"{MODULE}.set_cache", new=AsyncMock()) as set_cache,
        patch(f"{MODULE}.delete_cache", new=AsyncMock()) as delete_cache,
    ):
        users.find_one = AsyncMock(return_value={"hil_preferences": {}})
        users.update_one = AsyncMock()
        yield {
            "users": users,
            "get_cache": get_cache,
            "set_cache": set_cache,
            "delete_cache": delete_cache,
        }


def update_document(store: dict) -> Any:
    """The second positional arg of the last update_one — the ``$set`` doc or pipeline."""
    return store["users"].update_one.await_args.args[1]


def overrides_stage(store: dict) -> dict:
    """The ``$setField`` spec inside a per-tool pipeline update."""
    pipeline = update_document(store)
    assert isinstance(pipeline, list), "a per-tool write must be a pipeline, not a $set doc"
    return pipeline[0]["$set"]["hil_preferences.tool_overrides"]["$setField"]


class TestReadThroughCache:
    async def test_a_cache_hit_never_touches_mongo(self, store: dict) -> None:
        store["get_cache"].return_value = {"mode": "auto", "tool_overrides": {"send": True}}

        prefs = await get_hil_preferences(USER_ID)

        assert prefs.mode == "auto"
        assert prefs.tool_overrides == {"send": True}
        store["users"].find_one.assert_not_awaited()

    async def test_a_cache_miss_reads_mongo_and_populates_the_cache(self, store: dict) -> None:
        store["users"].find_one.return_value = {"hil_preferences": {"mode": "always_ask"}}

        prefs = await get_hil_preferences(USER_ID)

        assert prefs.mode == "always_ask"
        store["set_cache"].assert_awaited_once()
        assert store["set_cache"].await_args.args[1]["mode"] == "always_ask"

    async def test_a_user_who_never_set_preferences_gets_the_defaults(self, store: dict) -> None:
        # A brand-new user has no `hil_preferences` key at all. Crashing here would break
        # every tool call for everyone who has not opened settings.
        store["users"].find_one.return_value = {"email": "x@y.z"}

        prefs = await get_hil_preferences(USER_ID)

        assert prefs == HILPreferences()

    async def test_a_missing_user_document_does_not_crash_the_gate(self, store: dict) -> None:
        store["users"].find_one.return_value = None

        assert await get_hil_preferences(USER_ID) == HILPreferences()

    async def test_the_lookup_is_scoped_to_this_user(self, store: dict) -> None:
        await get_hil_preferences(USER_ID)

        assert store["users"].find_one.await_args.args[0] == {"_id": ObjectId(USER_ID)}


class TestPerToolOverride:
    """The concurrency-safe write. Each assertion here maps to a way the previous
    read-modify-write could silently drop a user's setting."""

    async def test_setting_an_override_writes_only_that_tools_key(self, store: dict) -> None:
        # The whole point: the update names ONE field. A write that carried the whole map
        # would clobber any sibling toggle that landed while this request was in flight.
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        spec = overrides_stage(store)
        assert spec["field"] == {"$literal": "GMAIL_SEND_EMAIL"}
        assert spec["value"] is True

    async def test_clearing_an_override_removes_only_that_key(self, store: dict) -> None:
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", None)

        assert overrides_stage(store)["value"] == "$$REMOVE"

    async def test_an_override_can_be_set_to_never_ask(self, store: dict) -> None:
        # False is a real setting ("always allow this tool"), not an absent one. Coercing
        # it to a clear would silently re-gate a tool the user disarmed.
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", False)

        spec = overrides_stage(store)
        assert spec["value"] is False
        assert spec["value"] != "$$REMOVE"

    async def test_a_dotted_mcp_tool_name_stays_a_flat_key(self, store: dict) -> None:
        # A dotted `$set` path would make Mongo nest {"server": {"action": true}}, which
        # the flat-map read path never finds — the toggle would appear to do nothing.
        await set_tool_override(USER_ID, "server.action", True)

        pipeline = update_document(store)
        assert "hil_preferences.tool_overrides.server.action" not in pipeline[0]["$set"]
        assert overrides_stage(store)["field"] == {"$literal": "server.action"}

    async def test_a_tool_name_starting_with_a_dollar_is_not_read_as_a_field_path(
        self, store: dict
    ) -> None:
        # `$literal` is why this is safe. A bare string would be resolved as an expression.
        await set_tool_override(USER_ID, "$weird_tool", True)

        assert overrides_stage(store)["field"] == {"$literal": "$weird_tool"}

    async def test_the_existing_map_is_preserved_rather_than_replaced(self, store: dict) -> None:
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        assert overrides_stage(store)["input"] == {
            "$ifNull": ["$hil_preferences.tool_overrides", {}]
        }

    async def test_the_cache_is_invalidated_so_the_next_gate_check_sees_the_change(
        self, store: dict
    ) -> None:
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        store["delete_cache"].assert_awaited_once()

    async def test_the_write_is_scoped_to_this_user(self, store: dict) -> None:
        await set_tool_override(USER_ID, "GMAIL_SEND_EMAIL", True)

        assert store["users"].update_one.await_args.args[0] == {"_id": ObjectId(USER_ID)}


class TestPartialUpdate:
    async def test_updating_the_mode_alone_leaves_the_overrides_untouched(
        self, store: dict
    ) -> None:
        await update_hil_preferences(USER_ID, mode="auto")

        assert update_document(store) == {"$set": {"hil_preferences.mode": "auto"}}

    async def test_updating_the_overrides_alone_leaves_the_mode_untouched(
        self, store: dict
    ) -> None:
        await update_hil_preferences(USER_ID, tool_overrides={"send": True})

        assert update_document(store) == {
            "$set": {"hil_preferences.tool_overrides": {"send": True}}
        }

    async def test_an_empty_map_clears_the_overrides_rather_than_being_ignored(
        self, store: dict
    ) -> None:
        # {} is a real instruction ("reset every tool to its default"), and `if
        # tool_overrides is not None` is what distinguishes it from "not supplied".
        await update_hil_preferences(USER_ID, tool_overrides={})

        assert update_document(store) == {"$set": {"hil_preferences.tool_overrides": {}}}

    async def test_supplying_nothing_writes_nothing(self, store: dict) -> None:
        await update_hil_preferences(USER_ID)

        store["users"].update_one.assert_not_awaited()
        store["delete_cache"].assert_not_awaited()
