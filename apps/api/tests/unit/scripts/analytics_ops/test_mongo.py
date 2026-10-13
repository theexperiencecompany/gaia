"""Ground truth must come from the deployment whose PostHog project the run writes to."""

from __future__ import annotations

import pytest
from scripts.analytics_ops.mongo import require_mongo_for
from scripts.analytics_ops.posthog_api import TargetName

LOCAL = "mongodb://localhost:27017"
REMOTE = "mongodb+srv://ro:pw@cluster0.example.mongodb.net/?retryWrites=true"


@pytest.mark.parametrize("uri", [LOCAL, "mongodb://127.0.0.1:27017", "mongodb://mongo:27017"])
def test_prod_writes_refuse_a_local_mongo(uri: str) -> None:
    with pytest.raises(SystemExit, match="prod"):
        require_mongo_for(TargetName.PROD, uri)


def test_test_project_writes_refuse_a_remote_mongo() -> None:
    with pytest.raises(SystemExit, match="e2e"):
        require_mongo_for(TargetName.E2E, REMOTE)


@pytest.mark.parametrize(("target", "uri"), [(TargetName.PROD, REMOTE), (TargetName.E2E, LOCAL)])
def test_a_matching_pair_passes(target: TargetName, uri: str) -> None:
    require_mongo_for(target, uri)
