"""Unit tests for app/services/integrations/marketplace.py.

UNIT: marketplace.py :: get_all_integrations
EXPECTED: Concurrently fetch MCP tool metadata + public custom integrations, build
          platform integration responses from OAUTH_INTEGRATIONS (skipping unavailable
          and category-mismatched ones), hydrate platform tools from the store, and
          return a MarketplaceResponse whose `integrations` is platform+custom sorted by
          (-display_priority, name), `featured` is the is_featured subset (same sort),
          and `total` is the integration count.
MECHANISM: log.set(...); gather(get_all_mcp_tools(), fetch_custom_integrations());
           per oauth_int -> skip if not available / category mismatch; from_oauth_integration;
           hydrate response.tools from store[id]["tools"]; sort; MarketplaceResponse.
MUST-CATCH:
  - include_custom_public default True -> custom docs ARE fetched on a bare call  [L22]
  - include_custom_public=False short-circuits fetch_custom (no find, empty custom) [L32]
  - the Mongo query is exactly {"source": "custom", "is_public": True} (+category)  [L36-38]
  - category != "all" gates the custom-query category key and the platform filter   [L37,L59]
  - cursor is sorted ("created_at", -1)                                             [L40]
  - a custom doc that fails to parse is skipped, valid siblings survive             [L43-46]
  - tool hydration reads t["name"]/t.get("description") from store["tools"]         [L65-73]
  - integrations + featured sorted by (-display_priority, name); total == count     [L78-86]
EQUIVALENT MUTANTS (allowed survivors, justified): none.

UNIT: marketplace.py :: get_integration_details
EXPECTED: Resolve an integration_id; return None if unresolved or neither platform nor
          custom; build a response from the platform OAuthIntegration or the custom doc
          (None on custom parse failure); hydrate stored tools only when the response has
          none; populate creator {name, picture} from the users collection when created_by
          is set and the user exists.
MECHANISM: get_tools(id); resolve(id); branch platform/custom/none; hydrate tools if
           stored_tools and not response.tools; if created_by -> find_one(ObjectId, proj).
MUST-CATCH:
  - resolve None -> returns None                                                    [L96-97]
  - platform branch builds from resolved.platform_integration                       [L99-100]
  - custom branch builds from custom_doc; parse failure -> None                     [L101-107]
  - neither platform nor custom -> None                                             [L108-109]
  - stored tools hydrate ONLY when response.tools empty (And, not Or)               [L111-114]
  - created_by truthy gates the users lookup; missing creator -> creator stays None [L116-127]
  - find_one queried by ObjectId(created_by) with {"name":1,"picture":1} projection [L118-122]
EQUIVALENT MUTANTS (allowed survivors, justified): none.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.models.oauth_models import OAuthIntegration
from app.services.integrations.integration_resolver import ResolvedIntegration
from app.services.integrations.marketplace import (
    get_all_integrations,
    get_integration_details,
)

MODULE = "app.services.integrations.marketplace"


def _make_async_cursor(docs: list[dict]) -> MagicMock:
    """Mock async cursor supporting `.sort(...)` chaining + `async for`."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor

    async def _aiter() -> object:
        for doc in docs:
            yield doc

    cursor.__aiter__ = lambda self: _aiter()
    return cursor


def _oauth(
    id: str = "gmail",
    name: str = "Gmail",
    category: str = "communication",
    *,
    available: bool = True,
    is_featured: bool = False,
    display_priority: int = 0,
) -> OAuthIntegration:
    """Real OAuthIntegration so from_oauth_integration runs production logic."""
    return OAuthIntegration(
        id=id,
        name=name,
        description=f"{name} integration",
        category=category,
        provider=id,
        scopes=[],
        available=available,
        is_featured=is_featured,
        display_priority=display_priority,
        managed_by="mcp",
    )


def _custom_doc(
    integration_id: str = "custom-1",
    name: str = "Custom One",
    category: str = "custom",
    *,
    is_featured: bool = False,
    display_priority: int = 0,
) -> dict:
    """A well-formed custom integration document (parses into Integration)."""
    return {
        "integration_id": integration_id,
        "name": name,
        "description": f"{name} desc",
        "category": category,
        "managed_by": "mcp",
        "source": "custom",
        "is_public": True,
        "created_by": None,
        "is_featured": is_featured,
        "display_priority": display_priority,
    }


def _store(tools_by_id: dict | None = None) -> AsyncMock:
    store = AsyncMock()
    store.get_all_mcp_tools.return_value = tools_by_id or {}
    return store


@pytest.fixture(autouse=True)
def _patch_log() -> object:
    with patch(f"{MODULE}.log"):
        yield


class TestGetAllIntegrations:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_empty_marketplace(self, mock_coll: MagicMock, mock_store_fn: MagicMock) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        assert result.total == 0
        assert result.integrations == []
        assert result.featured == []

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_oauth("gmail", "Gmail")])
    async def test_platform_integration_built_from_oauth(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        assert result.total == 1
        only = result.integrations[0]
        assert only.integration_id == "gmail"
        assert only.name == "Gmail"
        assert only.source == "platform"
        assert only.category == "communication"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_oauth("gmail", "Gmail", available=True), _oauth("zoom", "Zoom", available=False)],
    )
    async def test_unavailable_integration_excluded(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        names = {i.name for i in result.integrations}
        assert names == {"Gmail"}

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_oauth("gmail", "Gmail", "communication"), _oauth("github", "GitHub", "developer")],
    )
    async def test_category_filters_platform_integrations(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations(category="developer")

        assert [i.name for i in result.integrations] == ["GitHub"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [_oauth("gmail", "Gmail", "communication"), _oauth("github", "GitHub", "developer")],
    )
    async def test_category_all_keeps_every_platform_integration(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        # category == "all" must bypass the platform category filter (L59 `!= "all"`)
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations(category="all")

        assert {i.name for i in result.integrations} == {"Gmail", "GitHub"}
        # And it must NOT push a category key into the custom Mongo query (L37).
        query = mock_coll.find.call_args.args[0]
        assert query == {"source": "custom", "is_public": True}

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_custom_query_shape_and_sort_with_category(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        cursor = _make_async_cursor([])
        mock_coll.find.return_value = cursor

        await get_all_integrations(category="developer")

        # Exact query: base filter + the category key only because category != "all".
        assert mock_coll.find.call_args.args[0] == {
            "source": "custom",
            "is_public": True,
            "category": "developer",
        }
        # Newest-first sort on created_at.
        cursor.sort.assert_called_once_with("created_at", -1)

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_custom_integrations_fetched_by_default(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        # Bare call (include_custom_public defaults True, L22): custom docs are fetched
        # and surface in the response.
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([_custom_doc("c1", "Custom One")])

        result = await get_all_integrations()

        assert mock_coll.find.called
        assert [i.name for i in result.integrations] == ["Custom One"]
        assert result.integrations[0].source == "custom"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_exclude_custom_public_skips_db(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        # include_custom_public=False (L32): early return [] -> no DB hit, no custom rows
        # even though a doc exists.
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([_custom_doc("c1", "Custom One")])

        result = await get_all_integrations(include_custom_public=False)

        mock_coll.find.assert_not_called()
        assert result.total == 0

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [])
    async def test_unparseable_custom_doc_skipped(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        # First doc is missing required fields (raises in Integration(**doc)); the valid
        # second doc must still be returned (L43-46 try/except path).
        mock_store_fn.return_value = _store()
        bad = {"integration_id": "broken"}  # missing name/description/category/managed_by
        good = _custom_doc("c-good", "Good Custom")
        mock_coll.find.return_value = _make_async_cursor([bad, good])

        result = await get_all_integrations()

        assert [i.name for i in result.integrations] == ["Good Custom"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_oauth("gmail", "Gmail")])
    async def test_tools_hydrated_from_store(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store(
            {
                "gmail": {
                    "tools": [
                        {"name": "send_email", "description": "Send an email"},
                        {"name": "list_threads"},  # description omitted -> None
                    ],
                    "name": "Gmail",
                }
            }
        )
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        tools = result.integrations[0].tools
        assert [t.name for t in tools] == ["send_email", "list_threads"]
        assert tools[0].description == "Send an email"
        assert tools[1].description is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(f"{MODULE}.OAUTH_INTEGRATIONS", [_oauth("gmail", "Gmail")])
    async def test_no_tools_when_store_empty_for_integration(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        # store has an entry with an empty tools list -> response keeps no tools (L69 guard)
        mock_store_fn.return_value = _store({"gmail": {"tools": [], "name": "Gmail"}})
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        assert result.integrations[0].tools == []

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _oauth("a", "Aardvark", display_priority=1),
            _oauth("z", "Zebra", display_priority=10),
            _oauth("m", "Moose", display_priority=10),
        ],
    )
    async def test_integrations_sorted_by_priority_then_name(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        # -display_priority first (10 before 1), ties broken by name ascending.
        assert [i.name for i in result.integrations] == ["Moose", "Zebra", "Aardvark"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_mcp_tools_store")
    @patch(f"{MODULE}.integrations_collection")
    @patch(
        f"{MODULE}.OAUTH_INTEGRATIONS",
        [
            _oauth("gmail", "Gmail", is_featured=True, display_priority=5),
            _oauth("github", "GitHub", is_featured=True, display_priority=10),
            _oauth("slack", "Slack", is_featured=False, display_priority=99),
        ],
    )
    async def test_featured_subset_and_sort(
        self, mock_coll: MagicMock, mock_store_fn: MagicMock
    ) -> None:
        mock_store_fn.return_value = _store()
        mock_coll.find.return_value = _make_async_cursor([])

        result = await get_all_integrations()

        # Only is_featured entries, sorted by -priority then name. Slack excluded.
        assert [i.name for i in result.featured] == ["GitHub", "Gmail"]
        assert result.total == 3


class TestGetIntegrationDetails:
    @staticmethod
    def _resolved(
        *,
        platform: OAuthIntegration | None = None,
        custom_doc: dict | None = None,
    ) -> ResolvedIntegration:
        return ResolvedIntegration(
            integration_id="x",
            name="x",
            description="x",
            category="x",
            managed_by="mcp",
            source="platform" if platform else "custom",
            requires_auth=False,
            auth_type=None,
            mcp_config=None,
            platform_integration=platform,
            custom_doc=custom_doc,
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_unresolved_returns_none(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        mock_resolver.resolve = AsyncMock(return_value=None)

        assert await get_integration_details("nope") is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_neither_platform_nor_custom_returns_none(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(platform=None, custom_doc=None)
        )

        assert await get_integration_details("ghost") is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_platform_branch_builds_response(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(platform=_oauth("gmail", "Gmail", "communication"))
        )

        result = await get_integration_details("gmail")

        assert result is not None
        assert result.integration_id == "gmail"
        assert result.name == "Gmail"
        assert result.source == "platform"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_custom_branch_builds_response(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        doc = _custom_doc("custom-1", "Custom One", category="productivity")
        mock_resolver.resolve = AsyncMock(return_value=self._resolved(custom_doc=doc))

        result = await get_integration_details("custom-1")

        assert result is not None
        assert result.integration_id == "custom-1"
        assert result.name == "Custom One"
        assert result.source == "custom"

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_custom_branch_parse_failure_returns_none(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        # custom_doc missing required fields -> Integration(**doc) raises -> None (L102-107)
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(custom_doc={"integration_id": "broken"})
        )

        assert await get_integration_details("broken") is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_stored_tools_hydrated_when_response_empty(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = [
            {"name": "tool1", "description": "desc1"},
            {"name": "tool2"},
        ]
        mock_store_fn.return_value = store
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(platform=_oauth("gmail", "Gmail"))
        )

        result = await get_integration_details("gmail")

        assert result is not None
        assert [t.name for t in result.tools] == ["tool1", "tool2"]
        assert result.tools[0].description == "desc1"
        assert result.tools[1].description is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_stored_tools_not_hydrated_when_response_has_tools(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        # Response already carries tools (from a custom doc) AND store has tools.
        # `stored_tools and not response.tools` (L111) must be False -> no overwrite.
        # An `or` mutant would clobber the existing tools with the stored ones.
        store = AsyncMock()
        store.get_tools.return_value = [{"name": "from_store"}]
        mock_store_fn.return_value = store
        doc = _custom_doc("custom-1", "Custom One")
        doc["tools"] = [{"name": "from_doc", "description": "kept"}]
        mock_resolver.resolve = AsyncMock(return_value=self._resolved(custom_doc=doc))

        result = await get_integration_details("custom-1")

        assert result is not None
        assert [t.name for t in result.tools] == ["from_doc"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_no_tools_when_store_empty_and_response_empty(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        # stored_tools empty -> guard False -> tools stay empty (kills the str/`and` flip
        # only via the positive case, this pins the negative).
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(platform=_oauth("gmail", "Gmail"))
        )

        result = await get_integration_details("gmail")

        assert result is not None
        assert result.tools == []

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_creator_populated_from_users_collection(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        creator_id = "507f1f77bcf86cd799439011"  # pragma: allowlist secret
        doc = _custom_doc("custom-1", "Custom One")
        doc["created_by"] = creator_id
        mock_resolver.resolve = AsyncMock(return_value=self._resolved(custom_doc=doc))
        mock_users.find_one = AsyncMock(
            return_value={"name": "Ada", "picture": "https://pic/ada.png"}
        )

        result = await get_integration_details("custom-1")

        assert result is not None
        assert result.creator == {"name": "Ada", "picture": "https://pic/ada.png"}
        # Looked up by ObjectId(created_by) with the name/picture projection only.
        args, _ = mock_users.find_one.call_args
        assert args[0] == {"_id": ObjectId(creator_id)}
        assert args[1] == {"name": 1, "picture": 1}

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_creator_not_set_when_user_missing(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        # created_by set but user not found -> creator stays None (L123 `if creator_doc`).
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        doc = _custom_doc("custom-1", "Custom One")
        doc["created_by"] = "507f1f77bcf86cd799439011"  # pragma: allowlist secret
        mock_resolver.resolve = AsyncMock(return_value=self._resolved(custom_doc=doc))
        mock_users.find_one = AsyncMock(return_value=None)

        result = await get_integration_details("custom-1")

        assert result is not None
        assert result.creator is None

    @pytest.mark.asyncio
    @patch(f"{MODULE}.users_collection")
    @patch(f"{MODULE}.IntegrationResolver")
    @patch(f"{MODULE}.get_mcp_tools_store")
    async def test_no_creator_lookup_when_created_by_absent(
        self, mock_store_fn: MagicMock, mock_resolver: MagicMock, mock_users: MagicMock
    ) -> None:
        # Platform integrations have created_by None -> `if response.created_by` False ->
        # users collection is never queried (L116 guard).
        store = AsyncMock()
        store.get_tools.return_value = []
        mock_store_fn.return_value = store
        mock_users.find_one = AsyncMock()
        mock_resolver.resolve = AsyncMock(
            return_value=self._resolved(platform=_oauth("gmail", "Gmail"))
        )

        result = await get_integration_details("gmail")

        assert result is not None
        assert result.creator is None
        mock_users.find_one.assert_not_called()
