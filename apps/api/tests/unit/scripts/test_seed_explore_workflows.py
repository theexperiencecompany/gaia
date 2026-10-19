"""Unit tests for the explore-template seed: "system" stays a legitimate template owner.

Templates are the one kind of record "system" may own. The owner check on
TodoService and WorkflowService refuses it, so these pin that seeding still
writes system-owned templates and never routes through those services.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from scripts.seed_explore_workflows import get_all_workflows, seed_explore_workflows

from app.constants.vfs import SYSTEM_USER_ID
from app.models.workflow_models import WorkflowDocument

MODULE = "scripts.seed_explore_workflows"


def _collection() -> MagicMock:
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=0)
    collection.delete_many = AsyncMock()
    collection.insert_many = AsyncMock(
        side_effect=lambda docs: MagicMock(inserted_ids=[doc["_id"] for doc in docs])
    )
    return collection


class TestSeedExploreWorkflows:
    async def test_every_template_is_written_as_a_system_owned_explore_workflow(self) -> None:
        collection = _collection()
        with (
            patch(f"{MODULE}.workflows_collection", collection),
            patch(
                "app.utils.auth_utils.user_repository.get",
                AsyncMock(side_effect=AssertionError("seeding must not run the owner check")),
            ),
        ):
            await seed_explore_workflows(force=True, backup=False)

        (docs,) = collection.insert_many.await_args.args
        assert len(docs) == len(get_all_workflows())
        for doc in docs:
            template = WorkflowDocument.model_validate(doc)
            assert (template.user_id, template.created_by) == (SYSTEM_USER_ID, SYSTEM_USER_ID)
            assert template.is_explore is True

    async def test_a_dry_run_writes_nothing(self) -> None:
        collection = _collection()
        with patch(f"{MODULE}.workflows_collection", collection):
            await seed_explore_workflows(dry_run=True)

        collection.insert_many.assert_not_awaited()
        collection.delete_many.assert_not_awaited()
