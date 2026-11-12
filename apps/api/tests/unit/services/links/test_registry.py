"""Every link target type has exactly one spec, and the analytics catalog restates the API's sets exactly."""

from typing import get_args

import pytest

from app.models.short_link_models import (
    LinkAccess,
    LinkDenial,
    PublishRejection,
    RenderMode,
    ReportReason,
    RevokeReason,
    ShortLinkTargetType,
)
from app.services.links.registry import REGISTRY
from app.services.links.spec import build_registry
from shared.py.analytics.catalog import short_links as catalog


def test_every_target_type_has_its_own_spec() -> None:
    assert set(REGISTRY) == set(ShortLinkTargetType)
    assert all(spec.type is target_type for target_type, spec in REGISTRY.items())


def test_a_registry_missing_a_type_refuses_to_build() -> None:
    specs = tuple(
        spec for spec in REGISTRY.values() if spec.type is not ShortLinkTargetType.BRIEFING
    )
    with pytest.raises(ValueError, match="briefing"):
        build_registry(specs)


def test_a_type_with_two_specs_refuses_to_build() -> None:
    specs = (*REGISTRY.values(), REGISTRY[ShortLinkTargetType.BRIEFING])
    with pytest.raises(ValueError, match="two link target specs"):
        build_registry(specs)


@pytest.mark.parametrize(
    ("literal", "values"),
    [
        (catalog.ShortLinkTarget, {member.value for member in ShortLinkTargetType}),
        (catalog.ShortLinkAccess, {member.value for member in LinkAccess}),
        (catalog.ShortLinkRevokeReason, {member.value for member in RevokeReason}),
        (catalog.ShortLinkRenderMode, {member.value for member in RenderMode}),
        (catalog.ShortLinkPublishRejection, {member.value for member in PublishRejection}),
        (catalog.ShortLinkReportReason, {member.value for member in ReportReason}),
        # A denial event never fires for an unknown slug: there is no owner to count it for.
        (
            catalog.ShortLinkDenialReason,
            {
                member.value.removeprefix("link_")
                for member in LinkDenial
                if member is not LinkDenial.NOT_FOUND
            },
        ),
    ],
)
def test_the_catalog_restates_each_api_set_exactly(literal: object, values: set[str]) -> None:
    assert set(get_args(literal)) == values
