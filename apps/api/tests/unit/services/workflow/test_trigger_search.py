"""Trigger search enriches each semantic hit with the user's connection and the trigger's config."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.chroma.chroma_triggers_store import TRIGGERS_NAMESPACE
from app.models.trigger_config import (
    TriggerConfig,
    TriggerConfigFieldSchema,
    TriggerSearchConfigField,
    TriggerSearchResult,
    WorkflowTriggerSchema,
)
from app.services.workflow.trigger_search import TriggerSearchService

EVENT_CREATED = "GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER"
EVENT_SOON = "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER"
CALENDAR_ID = TriggerSearchConfigField(
    type="string",
    description="Calendar to monitor for new events",
    default="primary",
    required=False,
)


def _hit(slug: str, integration_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        value={
            "slug": slug,
            "name": f"{slug} name",
            "description": f"{slug} fires",
            "integration_id": integration_id,
            "integration_name": integration_id.title(),
            "embedding_text": "ignored",
        }
    )


async def _search(
    hits: list[SimpleNamespace], status: AsyncMock, *, limit: int = 15
) -> tuple[list[TriggerSearchResult], AsyncMock]:
    store = SimpleNamespace(asearch=AsyncMock(return_value=hits))
    with (
        patch(
            "app.services.workflow.trigger_search.get_triggers_store",
            new_callable=AsyncMock,
            return_value=store,
        ),
        patch("app.services.oauth.oauth_service.check_integration_status", new=status),
    ):
        results = await TriggerSearchService.search("new meeting", "u1", limit=limit)
    return results, store.asearch


class TestSearch:
    async def test_each_hit_carries_its_connection_and_config_fields(self) -> None:
        status = AsyncMock(return_value=True)

        results, asearch = await _search([_hit(EVENT_CREATED, "googlecalendar")], status, limit=3)

        asearch.assert_awaited_once_with((TRIGGERS_NAMESPACE,), query="new meeting", limit=3)
        assert results == [
            TriggerSearchResult(
                trigger_slug=EVENT_CREATED,
                trigger_name=f"{EVENT_CREATED} name",
                description=f"{EVENT_CREATED} fires",
                integration_id="googlecalendar",
                integration_name="Googlecalendar",
                is_connected=True,
                config_fields={"calendar_id": CALENDAR_ID},
            )
        ]

    async def test_the_connection_is_checked_once_per_integration(self) -> None:
        connected = {"googlecalendar": True, "gmail": False}
        status = AsyncMock(side_effect=lambda integration_id, _user: connected[integration_id])

        results, _ = await _search(
            [
                _hit(EVENT_CREATED, "googlecalendar"),
                _hit("GMAIL_NEW_GMAIL_MESSAGE", "gmail"),
                _hit(EVENT_SOON, "googlecalendar"),
            ],
            status,
        )

        assert [r.is_connected for r in results] == [True, False, True]
        assert [c.args for c in status.await_args_list] == [
            ("googlecalendar", "u1"),
            ("gmail", "u1"),
        ]

    async def test_a_failed_connection_check_reads_as_not_connected(self) -> None:
        status = AsyncMock(side_effect=RuntimeError("mongo down"))

        results, _ = await _search([_hit(EVENT_CREATED, "googlecalendar")], status)

        assert [r.is_connected for r in results] == [False]


def _integration(*triggers: TriggerConfig) -> SimpleNamespace:
    return SimpleNamespace(associated_triggers=list(triggers))


class TestConfigFields:
    def test_a_catalog_trigger_returns_its_config_schema(self) -> None:
        assert TriggerSearchService.config_fields(EVENT_CREATED) == {"calendar_id": CALENDAR_ID}

    def test_an_unknown_trigger_has_no_fields(self) -> None:
        assert TriggerSearchService.config_fields("NOT_A_TRIGGER") == {}

    @pytest.mark.parametrize("schema", [None, "empty"])
    def test_a_trigger_without_config_has_no_fields(self, schema: str | None) -> None:
        trigger = TriggerConfig(
            slug="T",
            name="T",
            description="d",
            workflow_trigger_schema=None
            if schema is None
            else WorkflowTriggerSchema(slug="t", composio_slug="T", name="T", description="d"),
        )
        with patch(
            "app.services.workflow.trigger_search.all_integrations",
            return_value=[_integration(), SimpleNamespace(associated_triggers=None)]
            + [_integration(trigger)],
        ):
            assert TriggerSearchService.config_fields("T") == {}

    def test_the_matching_trigger_is_found_past_earlier_ones(self) -> None:
        def _trigger(slug: str, default: int) -> TriggerConfig:
            return TriggerConfig(
                slug=slug,
                name=slug,
                description="d",
                workflow_trigger_schema=WorkflowTriggerSchema(
                    slug=slug.lower(),
                    composio_slug=slug,
                    name=slug,
                    description="d",
                    config_schema={
                        "minutes": TriggerConfigFieldSchema(
                            type="integer", default=default, description="lead time"
                        )
                    },
                ),
            )

        with patch(
            "app.services.workflow.trigger_search.all_integrations",
            return_value=[
                _integration(_trigger("A", 5)),
                _integration(_trigger("C", 1), _trigger("B", 10)),
            ],
        ):
            assert TriggerSearchService.config_fields("B") == {
                "minutes": TriggerSearchConfigField(
                    type="integer", description="lead time", default=10, required=False
                )
            }
