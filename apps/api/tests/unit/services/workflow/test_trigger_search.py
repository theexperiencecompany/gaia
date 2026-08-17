"""Unit tests for app.services.workflow.trigger_search.

``get_schema`` is what the workflow builder renders its trigger configuration
form from: an empty ``config_fields`` means the user is asked for nothing and
the trigger is created unconfigured.
"""

from app.services.workflow.trigger_search import TriggerSearchService


class TestGetSchema:
    async def test_config_fields_reach_the_returned_schema(self) -> None:
        schema = await TriggerSearchService.get_schema("GITHUB_COMMIT_EVENT")

        assert schema is not None
        config_fields = schema["config_fields"]
        assert isinstance(config_fields, dict)
        assert set(config_fields) == {"owner", "repo"}
        assert config_fields["owner"]["description"] == "Owner of the repository (username or org)"

    async def test_unknown_slug_returns_none(self) -> None:
        assert await TriggerSearchService.get_schema("NOT_A_TRIGGER") is None
