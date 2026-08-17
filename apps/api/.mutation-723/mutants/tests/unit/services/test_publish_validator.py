"""Unit tests for the publish validator (publish_validator).

Pure validation: name/description length bounds, tool cardinality, and the
LLM-backed profanity check — all returned as ordered error strings.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.integrations.publish_validator import PublishIntegrationValidator

_MOD = "app.services.integrations.publish_validator"


@pytest.fixture
def mock_profanity():
    with patch(f"{_MOD}.contains_profanity", new_callable=AsyncMock) as m:
        m.return_value = False
        yield m


class TestPublishIntegrationValidator:
    async def test_valid_integration_passes(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="My Tool", description="Does things", tools=[{"name": "do"}]
        )

        assert errors == []
        mock_profanity.assert_awaited_once_with(name="My Tool", description="Does things")

    async def test_name_too_short(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="ab", description=None, tools=[{"name": "do"}]
        )

        assert errors == ["Name must be at least 3 characters"]

    async def test_name_too_long(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="x" * 101, description=None, tools=[{"name": "do"}]
        )

        assert errors == ["Name must be at most 100 characters"]

    async def test_empty_name(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="", description=None, tools=[{"name": "do"}]
        )

        assert errors == ["Name must be at least 3 characters"]

    async def test_description_too_long(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="Valid", description="y" * 501, tools=[{"name": "do"}]
        )

        assert errors == ["Description must be at most 500 characters"]

    async def test_missing_tools(self, mock_profanity):
        errors = await PublishIntegrationValidator.validate_for_publish(
            name="Valid", description=None, tools=[]
        )

        assert errors == ["Integration must have at least one tool to be published"]

    async def test_profanity_flagged(self, mock_profanity):
        mock_profanity.return_value = True

        errors = await PublishIntegrationValidator.validate_for_publish(
            name="Valid", description="scurrilous", tools=[{"name": "do"}]
        )

        assert errors == ["Content contains profanity"]

    async def test_errors_accumulate_in_order(self, mock_profanity):
        mock_profanity.return_value = True

        errors = await PublishIntegrationValidator.validate_for_publish(
            name="ab", description="y" * 501, tools=[]
        )

        assert errors == [
            "Name must be at least 3 characters",
            "Content contains profanity",
            "Description must be at most 500 characters",
            "Integration must have at least one tool to be published",
        ]
