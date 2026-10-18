"""Marketplace copy offers event triggers only for integrations that have them."""

import re

import pytest

from app.config.oauth_config import OAUTH_INTEGRATIONS

TRIGGER_CLAIM = re.compile(r"\bTrigger GAIA workflows when\b|\bSet up [\w ]+ triggers\b")


def _copy(integration_id: str) -> list[str]:
    integration = next(i for i in OAUTH_INTEGRATIONS if i.id == integration_id)
    content = integration.content
    if content is None:
        return []
    return [
        *content.use_cases,
        *(step.body for step in content.how_it_works),
        *(faq.answer for faq in content.faqs),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "integration_id",
    [i.id for i in OAUTH_INTEGRATIONS if not i.associated_triggers],
)
def test_copy_claims_no_trigger_the_integration_lacks(integration_id: str) -> None:
    assert [text for text in _copy(integration_id) if TRIGGER_CLAIM.search(text)] == []
