"""Unit tests for trigger utility functions."""

from typing import List
from unittest.mock import patch

import pytest

from app.models.trigger_config import TriggerConfig, WorkflowTriggerSchema
from app.utils.trigger_utils import (
    get_all_trigger_types,
    get_integration_for_trigger,
    has_integration_triggers,
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
        triggers: List[TriggerConfig],
    ) -> None:
        self.id = integration_id
        self.associated_triggers = triggers


# ---------------------------------------------------------------------------
# has_integration_triggers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasIntegrationTriggers:
    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_match_found(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "googlecalendar",
                    [_make_trigger("calendar_event_created")],
                ),
            ]
        )
        assert has_integration_triggers("calendar_event_created") is True

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_no_match(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "googlecalendar",
                    [_make_trigger("calendar_event_created")],
                ),
            ]
        )
        assert has_integration_triggers("unknown_trigger") is False

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_empty_integrations(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter([])  # type: ignore[method-assign, misc, assignment]
        assert has_integration_triggers("anything") is False

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_integration_with_no_triggers(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter([_FakeIntegration("slack", [])])  # type: ignore[method-assign, misc, assignment]
        assert has_integration_triggers("slack_message") is False

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_trigger_without_schema_skipped(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [_make_trigger("pr_opened", with_schema=False)],
                ),
            ]
        )
        assert has_integration_triggers("pr_opened") is False

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_multiple_integrations_match_in_second(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "slack",
                    [_make_trigger("slack_message_received")],
                ),
                _FakeIntegration(
                    "github",
                    [_make_trigger("github_pr_opened")],
                ),
            ]
        )
        assert has_integration_triggers("github_pr_opened") is True

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_multiple_triggers_per_integration(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "googlecalendar",
                    [
                        _make_trigger("calendar_event_created"),
                        _make_trigger("calendar_event_updated"),
                    ],
                ),
            ]
        )
        assert has_integration_triggers("calendar_event_updated") is True

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_mixed_triggers_with_and_without_schema(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [
                        _make_trigger("no_schema_trigger", with_schema=False),
                        _make_trigger("real_trigger"),
                    ],
                ),
            ]
        )
        assert has_integration_triggers("real_trigger") is True
        # The one without schema should not match
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [
                        _make_trigger("no_schema_trigger", with_schema=False),
                        _make_trigger("real_trigger"),
                    ],
                ),
            ]
        )
        assert has_integration_triggers("no_schema_trigger") is False


# ---------------------------------------------------------------------------
# get_integration_for_trigger
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetIntegrationForTrigger:
    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_match_returns_integration_id(
        self, mock_integrations: List[object]
    ) -> None:
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
    def test_no_match_returns_none(self, mock_integrations: List[object]) -> None:
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
    def test_empty_integrations_returns_none(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter([])  # type: ignore[method-assign, misc, assignment]
        assert get_integration_for_trigger("anything") is None

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_trigger_without_schema_returns_none(
        self, mock_integrations: List[object]
    ) -> None:
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
    def test_returns_first_matching_integration(
        self, mock_integrations: List[object]
    ) -> None:
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
    def test_integration_with_empty_triggers(
        self, mock_integrations: List[object]
    ) -> None:
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


# ---------------------------------------------------------------------------
# get_all_trigger_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllTriggerTypes:
    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_non_empty_result(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "googlecalendar",
                    [
                        _make_trigger("calendar_event_created"),
                        _make_trigger("calendar_event_updated"),
                    ],
                ),
                _FakeIntegration(
                    "github",
                    [_make_trigger("github_pr_opened")],
                ),
            ]
        )
        result = get_all_trigger_types()
        assert result == {
            "calendar_event_created",
            "calendar_event_updated",
            "github_pr_opened",
        }

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_empty_integrations(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter([])  # type: ignore[method-assign, misc, assignment]
        result = get_all_trigger_types()
        assert result == set()

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_mixed_with_and_without_schemas(
        self, mock_integrations: List[object]
    ) -> None:
        """Only triggers with a workflow_trigger_schema are included."""
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [
                        _make_trigger("github_pr_opened"),
                        _make_trigger("no_schema", with_schema=False),
                    ],
                ),
            ]
        )
        result = get_all_trigger_types()
        assert result == {"github_pr_opened"}

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_all_triggers_without_schemas(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [
                        _make_trigger("a", with_schema=False),
                        _make_trigger("b", with_schema=False),
                    ],
                ),
            ]
        )
        result = get_all_trigger_types()
        assert result == set()

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_integrations_with_no_triggers(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration("slack", []),
                _FakeIntegration("notion", []),
            ]
        )
        result = get_all_trigger_types()
        assert result == set()

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_duplicate_slugs_across_integrations_deduplicated(
        self, mock_integrations: List[object]
    ) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "integration_a",
                    [_make_trigger("shared_slug")],
                ),
                _FakeIntegration(
                    "integration_b",
                    [_make_trigger("shared_slug")],
                ),
            ]
        )
        result = get_all_trigger_types()
        assert result == {"shared_slug"}
        assert len(result) == 1

    @patch("app.utils.trigger_utils.OAUTH_INTEGRATIONS")
    def test_returns_set_type(self, mock_integrations: List[object]) -> None:
        mock_integrations.__iter__ = lambda self: iter(  # type: ignore[method-assign, misc, assignment]
            [
                _FakeIntegration(
                    "github",
                    [_make_trigger("github_push")],
                ),
            ]
        )
        result = get_all_trigger_types()
        assert isinstance(result, set)
