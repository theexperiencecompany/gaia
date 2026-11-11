"""Catalogue invariants that only show up across entries, not within one."""

from urllib.parse import urlparse

import pytest

from app.config.oauth_config import all_integrations


def test_every_integration_id_is_unique() -> None:
    ids = [integration.id for integration in all_integrations()]

    assert len(ids) == len(set(ids))


@pytest.mark.regression
def test_every_mcp_server_url_is_ours_and_parameterless() -> None:
    """A Composio URL carrying someone else's user_id is a server we cannot reach."""
    urls = [
        integration.mcp_config.server_url
        for integration in all_integrations()
        if integration.mcp_config is not None
    ]

    for url in urls:
        parsed = urlparse(url)
        assert parsed.scheme == "https", url
        assert "user_id=" not in url, url


def test_every_subagent_agent_name_is_unique() -> None:
    names = [
        integration.subagent_config.agent_name
        for integration in all_integrations()
        if integration.subagent_config is not None
    ]

    assert len(names) == len(set(names))
