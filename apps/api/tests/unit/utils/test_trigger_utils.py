"""Unit tests for trigger utility functions."""

from unittest.mock import patch

import pytest

from app.models.trigger_config import TriggerConfig, WorkflowTriggerSchema
from app.utils.trigger_utils import (
    get_integration_for_trigger,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight fakes that match the OAuthIntegration shape
# ---------------------------------------------------------------------------


def _make_trigger(
    slug: str,
    composio_slug: str = "COMPOSIO_SLUG",
    name: str = "Trigger",
    description: str = "A trigger",
    with_schema: bool = True,
) -> TriggerConfig:
    """Build a TriggerConfig, optionally without a workflow_trigger_schema."""
    schema = (
        WorkflowTriggerSchema(
            slug=slug,
            composio_slug=composio_slug,
            name=name,
            description=description,
        )
        if with_schema
        else None
    )
    return TriggerConfig(
        slug=composio_slug,
        name=name,
        description=description,
        workflow_trigger_schema=schema,
    )


class _FakeIntegration:
    """Minimal stand-in for OAuthIntegration used by trigger_utils."""

    def __init__(
        self,
        integration_id: str,
        triggers: list[TriggerConfig],
    ) -> None:
        self.id = integration_id
        self.associated_triggers = triggers


# ---------------------------------------------------------------------------
# get_integration_for_trigger
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetIntegrationForTrigger:
    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_match_returns_integration_id(self, mock_integrations: list[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "googlecalendar",
                    [_make_trigger("calendar_event_created")],
                ),
            ]
        )
        assert get_integration_for_trigger("calendar_event_created") == "googlecalendar"

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_no_match_returns_none(self, mock_integrations: list[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "slack",
                    [_make_trigger("slack_message")],
                ),
            ]
        )
        assert get_integration_for_trigger("nonexistent") is None

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_empty_integrations_returns_none(self, mock_integrations: list[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter([])  # type: ignore[method-assign, misc, assignment]
        assert get_integration_for_trigger("anything") is None

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_trigger_without_schema_returns_none(self, mock_integrations: list[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [_make_trigger("pr_opened", with_schema=False)],
                ),
            ]
        )
        assert get_integration_for_trigger("pr_opened") is None

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_returns_first_matching_integration(self, mock_integrations: list[object]) -> None:
        """When the same slug appears in multiple integrations, the first wins."""
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "integration_a",
                    [_make_trigger("shared_trigger")],
                ),
                _FakeIntegration(
                    "integration_b",
                    [_make_trigger("shared_trigger")],
                ),
            ]
        )
        assert get_integration_for_trigger("shared_trigger") == "integration_a"

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_integration_with_empty_triggers(self, mock_integrations: list[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration("slack", []),
                _FakeIntegration(
                    "github",
                    [_make_trigger("github_push")],
                ),
            ]
        )
        assert get_integration_for_trigger("github_push") == "github"
