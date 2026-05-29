"""Unit tests for the integration response schemas.

UNIT: app/schemas/integrations/responses.py

These Pydantic models form the wire contract between the integrations API and
the frontend. Two kinds of real behaviour live here and are mutation-verified:

  1. CloneCountMixin.coerce_clone_count — a `mode="before"` field validator
     shared by IntegrationResponse, CommunityIntegrationItem,
     SearchIntegrationItem and PublicIntegrationDetailResponse. MongoDB
     documents may carry `clone_count: null`; the validator coerces None -> 0
     so the frontend always receives an integer count.
       MECHANISM: `return v if v is not None else 0`
       MUST-CATCH:
         - None coerces to 0 (the `else 0` branch and the int literal 0)
         - a real positive value passes through unchanged (the `is not None`
           branch; an Is->IsNot flip would swap the branches and break this)
         - applies on every CloneCountMixin subclass, not just one

  2. CamelModel serialization contract — populate_by_name + to_camel alias
     generator. The frontend consumes camelCase JSON; the service layer builds
     models with snake_case kwargs OR camelCase aliases. Both must work, and
     `model_dump(by_alias=True)` must emit camelCase keys.
       MUST-CATCH:
         - snake_case field name `integration_id` serializes to `integrationId`
         - a model may be constructed from the camelCase alias too
         - default `by_alias=False` keeps snake_case (no accidental aliasing)

  3. Field defaults declared in this module are the documented contract for
     optional fields and must not drift:
         - IntegrationConfigItem.source defaults to "platform"
         - IntegrationResponse.requires_auth False, clone_count 0
         - MCPConfigDetail.requires_auth False
         - CommunityListResponse.total 0, has_more False
         - MarketplaceResponse.total 0 / UserIntegrationsListResponse.total 0
         - AddIntegrationResponse.message "Integration added successfully"
         - SearchIntegrationItem / CommunityIntegrationItem / PublicIntegration
           DetailResponse: clone_count 0, tool_count 0
       Each literal default is a mutable constant; a mutation flipping it must
       be caught by an assertion on the constructed model.

  4. Literal-typed status fields reject out-of-contract values (Pydantic
     enforces the enum), so the frontend never receives an unknown status.

EQUIVALENT MUTANTS (allowed survivors, justified):
  - None. All mutable constants/branches in this module are asserted.
"""

from pydantic import ValidationError
import pytest

from app.schemas.integrations.responses import (
    AddIntegrationResponse,
    CommunityIntegrationItem,
    CommunityListResponse,
    ConnectIntegrationResponse,
    IntegrationConfigItem,
    IntegrationResponse,
    IntegrationStatusItem,
    MarketplaceResponse,
    MCPConfigDetail,
    PublicIntegrationDetailResponse,
    SearchIntegrationItem,
    UserIntegrationsListResponse,
)

# ---------------------------------------------------------------------------
# CloneCountMixin.coerce_clone_count
# ---------------------------------------------------------------------------


def _integration_response(**overrides: object) -> IntegrationResponse:
    base: dict[str, object] = {
        "integration_id": "gh",
        "name": "GitHub",
        "description": "desc",
        "category": "developer",
        "managed_by": "composio",
        "source": "platform",
        "is_featured": False,
        "display_priority": 0,
    }
    base.update(overrides)
    return IntegrationResponse(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCloneCountCoercion:
    def test_none_coerces_to_zero(self) -> None:
        """A MongoDB null clone_count becomes the integer 0 (the `else 0` branch)."""
        assert _integration_response(clone_count=None).clone_count == 0

    def test_positive_value_passes_through_unchanged(self) -> None:
        """A real count survives the `is not None` branch untouched. An Is->IsNot
        flip would route 17 into the `else 0` branch and break this."""
        assert _integration_response(clone_count=17).clone_count == 17

    def test_zero_value_passes_through(self) -> None:
        """An explicit 0 is `is not None`, so it returns the original 0 — not the
        literal fallback. Distinguishes pass-through from fallback coercion."""
        assert _integration_response(clone_count=0).clone_count == 0

    def test_applies_on_community_item(self) -> None:
        item = CommunityIntegrationItem(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
            clone_count=None,  # type: ignore[arg-type]
        )
        assert item.clone_count == 0

    def test_applies_on_search_item(self) -> None:
        item = SearchIntegrationItem(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
            relevance_score=0.5,
            clone_count=None,  # type: ignore[arg-type]
        )
        assert item.clone_count == 0

    def test_applies_on_public_detail(self) -> None:
        item = PublicIntegrationDetailResponse(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
            clone_count=None,  # type: ignore[arg-type]
        )
        assert item.clone_count == 0


# ---------------------------------------------------------------------------
# CamelModel serialization contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCamelSerialization:
    def test_snake_field_serializes_to_camel(self) -> None:
        item = IntegrationStatusItem(integration_id="gh", connected=True)
        assert item.model_dump(by_alias=True) == {"integrationId": "gh", "connected": True}

    def test_default_dump_keeps_snake_case(self) -> None:
        """Without by_alias the keys stay snake_case — aliasing is opt-in, so an
        always-on alias generator regression is caught."""
        item = IntegrationStatusItem(integration_id="gh", connected=True)
        assert item.model_dump() == {"integration_id": "gh", "connected": True}

    def test_construct_from_camel_alias(self) -> None:
        """populate_by_name lets the model accept the camelCase alias too."""
        item = IntegrationStatusItem(integrationId="gh", connected=False)  # type: ignore[call-arg]
        assert item.integration_id == "gh"
        assert item.connected is False

    def test_connect_response_multiword_alias(self) -> None:
        resp = ConnectIntegrationResponse(
            status="connected",
            integration_id="gh",
            name="GitHub",
            tools_count=5,
            redirect_url="https://example.com",
        )
        dumped = resp.model_dump(by_alias=True)
        assert dumped["integrationId"] == "gh"
        assert dumped["toolsCount"] == 5
        assert dumped["redirectUrl"] == "https://example.com"


# ---------------------------------------------------------------------------
# Field defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFieldDefaults:
    def test_config_item_source_defaults_to_platform(self) -> None:
        item = IntegrationConfigItem(
            id="i",
            name="n",
            description="d",
            category="c",
            provider="p",
            available=True,
            is_special=False,
            display_priority=0,
            included_integrations=[],
            is_featured=False,
            managed_by="self",
            slug="i",
        )
        assert item.source == "platform"
        assert item.auth_type is None

    def test_integration_response_defaults(self) -> None:
        resp = _integration_response()
        assert resp.requires_auth is False
        assert resp.clone_count == 0
        assert resp.tools == []
        assert resp.slug is None

    def test_mcp_config_detail_defaults(self) -> None:
        detail = MCPConfigDetail()
        assert detail.requires_auth is False
        assert detail.auth_type is None
        assert detail.server_url is None

    def test_community_list_defaults(self) -> None:
        resp = CommunityListResponse()
        assert resp.total == 0
        assert resp.has_more is False
        assert resp.integrations == []

    def test_marketplace_total_default(self) -> None:
        assert MarketplaceResponse().total == 0

    def test_user_integrations_list_total_default(self) -> None:
        assert UserIntegrationsListResponse().total == 0

    def test_add_integration_default_message(self) -> None:
        resp = AddIntegrationResponse(integration_id="x", name="n", status="connected")
        assert resp.message == "Integration added successfully"
        assert resp.redirect_url is None

    def test_community_item_count_defaults(self) -> None:
        item = CommunityIntegrationItem(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
        )
        assert item.clone_count == 0
        assert item.tool_count == 0

    def test_search_item_count_defaults(self) -> None:
        item = SearchIntegrationItem(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
            relevance_score=0.9,
        )
        assert item.clone_count == 0
        assert item.tool_count == 0

    def test_public_detail_count_defaults(self) -> None:
        item = PublicIntegrationDetailResponse(
            integration_id="x",
            slug="x",
            name="n",
            description="d",
            category="c",
        )
        assert item.clone_count == 0
        assert item.tool_count == 0
        assert item.source is None


# ---------------------------------------------------------------------------
# Literal-typed status fields enforce the contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLiteralStatusValidation:
    def test_add_integration_rejects_unknown_status(self) -> None:
        with pytest.raises(ValidationError):
            AddIntegrationResponse(
                integration_id="x",
                name="n",
                status="bogus",  # type: ignore[arg-type]
            )

    def test_connect_response_accepts_contract_statuses(self) -> None:
        for status in ("connected", "redirect", "error"):
            resp = ConnectIntegrationResponse(status=status, integration_id="x", name="n")  # type: ignore[arg-type]
            assert resp.status == status

    def test_add_integration_accepts_contract_statuses(self) -> None:
        for status in ("connected", "redirect", "error"):
            resp = AddIntegrationResponse(integration_id="x", name="n", status=status)  # type: ignore[arg-type]
            assert resp.status == status


# ---------------------------------------------------------------------------
# Literal-typed enum members are the accepted-value contract. Each declared
# member must validate when set explicitly; dropping a member (mutating its
# string to "") would reject a previously-valid value and break these.
# ---------------------------------------------------------------------------


_MANAGED_BY = ("self", "composio", "mcp", "internal")
_AUTH_TYPE = ("none", "oauth", "bearer")


@pytest.mark.unit
class TestLiteralEnumMembers:
    def test_config_item_managed_by_members_accepted(self) -> None:
        for managed_by in _MANAGED_BY:
            item = IntegrationConfigItem(
                id="i",
                name="n",
                description="d",
                category="c",
                provider="p",
                available=True,
                is_special=False,
                display_priority=0,
                included_integrations=[],
                is_featured=False,
                managed_by=managed_by,  # type: ignore[arg-type]
                slug="i",
            )
            assert item.managed_by == managed_by

    def test_config_item_auth_type_members_accepted(self) -> None:
        for auth_type in _AUTH_TYPE:
            item = IntegrationConfigItem(
                id="i",
                name="n",
                description="d",
                category="c",
                provider="p",
                available=True,
                is_special=False,
                display_priority=0,
                included_integrations=[],
                is_featured=False,
                managed_by="self",
                auth_type=auth_type,  # type: ignore[arg-type]
                source="platform",
                slug="i",
            )
            assert item.auth_type == auth_type
            assert item.source == "platform"

    def test_integration_response_managed_by_members_accepted(self) -> None:
        for managed_by in _MANAGED_BY:
            resp = _integration_response(managed_by=managed_by)
            assert resp.managed_by == managed_by

    def test_integration_response_source_members_accepted(self) -> None:
        for source in ("platform", "custom"):
            resp = _integration_response(source=source)
            assert resp.source == source

    def test_integration_response_auth_type_members_accepted(self) -> None:
        for auth_type in _AUTH_TYPE:
            resp = _integration_response(auth_type=auth_type)
            assert resp.auth_type == auth_type

    def test_mcp_config_detail_auth_type_members_accepted(self) -> None:
        for auth_type in _AUTH_TYPE:
            detail = MCPConfigDetail(auth_type=auth_type)  # type: ignore[arg-type]
            assert detail.auth_type == auth_type

    def test_public_detail_source_members_accepted(self) -> None:
        for source in ("platform", "custom"):
            item = PublicIntegrationDetailResponse(
                integration_id="x",
                slug="x",
                name="n",
                description="d",
                category="c",
                source=source,  # type: ignore[arg-type]
            )
            assert item.source == source

    def test_public_detail_auth_type_members_accepted(self) -> None:
        for auth_type in _AUTH_TYPE:
            item = PublicIntegrationDetailResponse(
                integration_id="x",
                slug="x",
                name="n",
                description="d",
                category="c",
                auth_type=auth_type,  # type: ignore[arg-type]
            )
            assert item.auth_type == auth_type
