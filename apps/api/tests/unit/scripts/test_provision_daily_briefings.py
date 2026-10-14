"""The existing-user briefing rollout boots like an entry point.

Regression: the rollout reports each user's path through capture(), which needs a bound
analytics context and a registered PostHog provider; without them every user failed.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from scripts.provision_daily_briefings import rollout

from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import current_analytics_context

MODULE = "scripts.provision_daily_briefings"


@pytest.fixture(autouse=True)
def _analytics_context() -> Iterator[None]:
    """Leave the context unbound: the script is an entry point and must bind its own."""
    return


async def _path_needing_a_context(user_id: str) -> str:
    assert current_analytics_context().attribution.trigger is Trigger.SYSTEM
    return "normal"


async def test_every_user_is_rolled_out_under_a_bound_analytics_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch(f"{MODULE}.register_lazy_providers") as register,
        patch(f"{MODULE}.user_repository.list_all_ids", AsyncMock(return_value=["u1", "u2"])),
        patch(f"{MODULE}.provision_existing_user", side_effect=_path_needing_a_context),
    ):
        await rollout(dry_run=False)

    # A script has no app lifespan: it registers the providers capture() and the
    # workflow provisioning read, or every user fails on "Provider not found".
    register.assert_called_once_with("main_app")
    assert "done: 2/2 rolled out; breakdown={'normal': 2}" in capsys.readouterr().out
