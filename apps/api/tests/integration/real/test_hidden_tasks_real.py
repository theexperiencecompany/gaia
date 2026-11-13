"""A hidden task is the agent's record of work: no read the user's own todo views make may count or list it. Real Mongo."""

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.constants.tasks import HIDDEN_TASK_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoSearchParams

pytestmark = pytest.mark.service

SHARED_LABEL = "trip"


@pytest.fixture
async def seeded(mongo_db: AsyncIOMotorDatabase, user_id: str) -> None:
    await todo_repository.create(
        TodoDocument(user_id=user_id, title="Book the train", labels=[SHARED_LABEL])
    )
    await todo_repository.create(
        TodoDocument(
            user_id=user_id, title="Find flights", labels=[HIDDEN_TASK_LABEL, SHARED_LABEL]
        )
    )


@pytest.mark.usefixtures("seeded")
class TestNoUserFacingReadSeesAHiddenTask:
    async def test_the_list_holds_only_the_visible_todo(self, user_id: str) -> None:
        params = TodoSearchParams()

        page = await todo_repository.list_page(
            user_id=user_id, params=params, inbox_project_id=None
        )

        assert [todo.title for todo in page.items] == ["Book the train"]
        assert page.total == 1

    async def test_the_stats_count_only_the_visible_todo(self, user_id: str) -> None:
        stats = await todo_repository.compute_stats(user_id=user_id)

        assert stats.total == 1

    async def test_the_top_labels_count_only_the_visible_todo(self, user_id: str) -> None:
        labels = await todo_repository.top_labels(user_id=user_id, limit=10)

        assert {label.name: label.count for label in labels} == {SHARED_LABEL: 1}

    async def test_the_usage_signal_counts_only_the_visible_todo(self, user_id: str) -> None:
        assert await todo_repository.count_for_user(user_id) == 1
