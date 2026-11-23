"""The todo delivery expand and contract migrations over real Mongo: each notify_on_run flag becomes its delivery."""

from collections.abc import AsyncIterator
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.workflows import WorkflowDelivery
from app.db.repositories.todos import todo_repository
from scripts import migrate_todo_delivery as migration

pytestmark = pytest.mark.service

USER = "user-1"
DESK_REF = {"source": "inbox_desk", "id": "gmail"}
THREAD_REF = {"source": "gmail_thread", "id": "18c2f0a9b7d4e611"}


@pytest.fixture
async def todos(mongo_db, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncIOMotorCollection]:
    """Point the migration and the todo repository at a fresh todos collection."""
    collection = mongo_db[f"todos_delivery_migration_{uuid.uuid4().hex}"]
    monkeypatch.setattr(migration, "todos_collection", collection)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: collection)
    yield collection
    await collection.drop()


async def _seed(todos: AsyncIOMotorCollection) -> dict[str, object]:
    docs: dict[str, dict[str, object]] = {
        "told": {"notify_on_run": True},
        "silent": {"notify_on_run": False},
        "desk": {"notify_on_run": True, "external_ref": DESK_REF},
        "silent_desk": {"notify_on_run": False, "external_ref": DESK_REF},
        "thread": {"notify_on_run": True, "external_ref": THREAD_REF},
        "migrated": {"notify_on_run": False, "delivery": "now"},
        "untouched": {"delivery": "silent"},
    }
    inserted = await todos.insert_many(
        [{"user_id": USER, "title": title, **fields} for title, fields in docs.items()]
    )
    return dict(zip(docs, inserted.inserted_ids, strict=True))


async def _delivery_by_title(todos: AsyncIOMotorCollection) -> dict[str, str | None]:
    return {doc["title"]: doc.get("delivery") async for doc in todos.find({})}


async def test_a_dry_run_counts_and_writes_nothing(todos: AsyncIOMotorCollection) -> None:
    await _seed(todos)
    before = [doc async for doc in todos.find({})]

    assert await migration.migrate(apply=False) == 5

    assert [doc async for doc in todos.find({})] == before


async def test_apply_maps_each_flag_to_its_delivery_and_keeps_the_flag(
    todos: AsyncIOMotorCollection,
) -> None:
    ids = await _seed(todos)

    assert await migration.migrate(apply=True) == 5

    assert await _delivery_by_title(todos) == {
        "told": "now",
        "silent": "silent",
        "desk": "brief",
        "silent_desk": "silent",
        "thread": "now",
        "migrated": "now",
        "untouched": "silent",
    }
    assert await todos.count_documents({"notify_on_run": {"$exists": True}}) == 6
    desk = await todo_repository.get(str(ids["desk"]), user_id=USER)
    assert desk is not None and desk.delivery is WorkflowDelivery.BRIEF


async def test_a_second_apply_finds_nothing_to_move(todos: AsyncIOMotorCollection) -> None:
    await _seed(todos)
    await migration.migrate(apply=True)
    after_first = [doc async for doc in todos.find({})]

    assert await migration.migrate(apply=True) == 0

    assert [doc async for doc in todos.find({})] == after_first


async def test_contract_maps_what_the_previous_release_wrote_since_then_drops_the_flag(
    todos: AsyncIOMotorCollection,
) -> None:
    await _seed(todos)
    await migration.migrate(apply=True)
    late = await todos.insert_one(
        {"user_id": USER, "title": "late", "notify_on_run": True, "external_ref": DESK_REF}
    )

    assert await migration.contract(apply=False) == 7
    assert await todos.count_documents({"notify_on_run": {"$exists": True}}) == 7

    assert await migration.contract(apply=True) == 7

    assert await todos.count_documents({"notify_on_run": {"$exists": True}}) == 0
    assert (await _delivery_by_title(todos))["late"] == "brief"
    stored = await todo_repository.get(str(late.inserted_id), user_id=USER)
    assert stored is not None and stored.delivery is WorkflowDelivery.BRIEF
    assert await migration.contract(apply=True) == 0
