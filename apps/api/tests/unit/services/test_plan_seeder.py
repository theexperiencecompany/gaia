"""seed_free_plan_if_missing must provision exactly the catalogue's Free row.

Instances without a payment provider (selfhost/dev) can never run the Dodo
setup script, so this seeder is what lets the startup gate pass. Idempotency
is load-bearing: a reboot with plans already present must not re-insert or
mutate the catalogue.

Mutation check: flip the ``count() > 0`` guard and the empty-collection test
fails (no seed happens); delete the guard and the existing-plans test fails
(create is awaited).
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.payment_models import PlanDocument
from app.services.bootstrap.plan_seeder import seed_free_plan_if_missing

MODULE = "app.services.bootstrap.plan_seeder"


@pytest.fixture
def mock_plan_repository() -> Iterator[MagicMock]:
    """Patch the repository singleton in the seeder's own namespace."""
    with patch(f"{MODULE}.plan_repository") as mock_repo:
        mock_repo.count = AsyncMock(return_value=0)
        # Mirror MongoRepository.create: persist and hand back the stored model.
        mock_repo.create = AsyncMock(side_effect=lambda doc: doc)
        yield mock_repo


class TestSeedFreePlanIfMissing:
    async def test_seeds_catalogue_free_row_when_collection_is_empty(
        self, mock_plan_repository: MagicMock
    ) -> None:
        assert await seed_free_plan_if_missing() is True

        mock_plan_repository.create.assert_awaited_once()
        seeded = mock_plan_repository.create.await_args.args[0]
        assert isinstance(seeded, PlanDocument)
        # Exactly the catalogue Free row: free of charge, active, monthly, and
        # carrying no Dodo product id.
        assert seeded.name == "Free"
        assert seeded.amount == 0
        assert seeded.is_active is True
        assert seeded.duration == "monthly"
        assert seeded.dodo_product_id == ""

    async def test_noop_when_plans_already_exist(self, mock_plan_repository: MagicMock) -> None:
        mock_plan_repository.count = AsyncMock(return_value=4)

        assert await seed_free_plan_if_missing() is False
        mock_plan_repository.create.assert_not_awaited()
