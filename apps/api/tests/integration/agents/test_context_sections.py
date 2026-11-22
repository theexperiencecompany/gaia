"""The two context sections with real behaviour behind them, un-mocked."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.agents.context.section_context import SectionContext
from app.agents.context.sections import SECTIONS, Section
from app.agents.context.slots import PromptSlot
from app.agents.context.text import EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER
from app.agents.context.tiers import AgentTier


@pytest.fixture
def user() -> str:
    """Build a user nobody has cached anything for.

    The integrations manifest sits behind a per-user @Cacheable and these tests
    mock the store one layer below that; a fixed id would make the result depend
    on whatever Redis happened to be holding.
    """
    return f"user-ctx-{uuid4()}"


def _ctx(user_id: str) -> SectionContext:
    return SectionContext(tier=AgentTier.EXECUTOR, user_id=user_id)


def _section(section_id: str) -> Section:
    return next(s for s in SECTIONS if s.id == section_id)


@pytest.mark.integration
class TestConnectedIntegrationsManifest:
    """Runs the real get_connected_integrations_named over mocked integration records."""

    @staticmethod
    def _records(*records: dict[str, str]):
        return patch(
            "app.services.integrations.user_integrations.get_user_integration_records",
            AsyncMock(return_value=list(records)),
        )

    async def test_only_connected_integrations_reach_the_agent(self, user: str) -> None:
        """A disconnected integration listed as available is worse than absent: its handoff fails."""
        with self._records(
            {"integration_id": "gmail", "status": "connected"},
            {"integration_id": "slack", "status": "disconnected"},
            {"integration_id": "notion", "status": "pending"},
        ):
            block = await _section("integrations_manifest").fetch(_ctx(user))

        assert "gmail" in block
        assert "slack" not in block
        assert "notion" not in block

    async def test_the_executor_gets_the_activation_framed_header(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "connected"}):
            block = await _section("integrations_manifest").fetch(_ctx(user))

        assert block.startswith(EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER)

    async def test_comms_gets_the_capability_framed_header_instead(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "connected"}):
            block = await _section("integrations_manifest").fetch(
                SectionContext(tier=AgentTier.COMMS, user_id=user)
            )

        assert not block.startswith(EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER)
        assert "gmail" in block

    async def test_no_connected_integrations_yields_nothing_at_all(self, user: str) -> None:
        with self._records({"integration_id": "gmail", "status": "disconnected"}):
            assert await _section("integrations_manifest").fetch(_ctx(user)) == ""

    async def test_the_manifest_is_a_stable_section(self) -> None:
        """It changes on connect/disconnect, never per turn, so it belongs in the cacheable prefix."""
        assert _section("integrations_manifest").slot is PromptSlot.DYNAMIC_STABLE
