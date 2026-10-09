"""Unit tests for the plans repository's tier backfill writes."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.plans import PlansRepository
from app.models.payment_models import PlanTier


class TestTagOneUntagged:
    @pytest.mark.parametrize(("matched", "tagged"), [(1, True), (0, False)])
    async def test_tags_one_untagged_row_of_that_name_in_the_global_scope(
        self, matched: int, tagged: bool
    ) -> None:
        repo = PlansRepository()
        with patch.object(
            repo, "_apply_raw_update_unfetched", new=AsyncMock(return_value=matched)
        ) as raw:
            result = await repo.tag_one_untagged("Pro", PlanTier.PRO)

        assert result is tagged
        raw.assert_awaited_once_with(
            {"name": "Pro", "plan_type": {"$exists": False}},
            {"$set": {"plan_type": "pro"}},
            scope=REPO_GLOBAL_SCOPE,
        )
