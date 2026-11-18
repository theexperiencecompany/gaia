"""The short-link target expand and contract migrations over real Mongo: old-shape links read as typed targets."""

from collections.abc import AsyncIterator
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.mongodb import indexes
from app.db.repositories.short_links import LIVE_TARGET_UNIQUE_INDEX, short_link_repository
from app.models.short_link_models import RecordTarget, ShortLinkTargetType, WorkspaceFileTarget
from scripts import migrate_short_link_targets as migration

OWNER = "owner-1"
TODO = RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id="t1")
FILE = WorkspaceFileTarget(
    type=ShortLinkTargetType.WORKSPACE_FILE, conversation_id="conv-1", path="reports/q3.html"
)


def _old(slug: str, target_type: str, target_id: str, **fields: object) -> dict[str, object]:
    return {
        "slug": slug,
        "user_id": OWNER,
        "target_type": target_type,
        "target_id": target_id,
        "revoked": False,
        **fields,
    }


@pytest.fixture
async def links(mongo_db, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncIOMotorCollection]:
    """Point every reader at a fresh short_links collection carrying the old-shape live-target index."""
    collection = mongo_db[f"short_links_migration_{uuid.uuid4().hex}"]
    for module in (migration, indexes):
        monkeypatch.setattr(module, "get_async_collection", lambda _name: collection)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: collection)
    await collection.create_index(
        [("user_id", 1), ("target_type", 1), ("target_id", 1)],
        unique=True,
        partialFilterExpression={"revoked": False},
        name=LIVE_TARGET_UNIQUE_INDEX,
    )
    yield collection
    await collection.drop()


async def test_old_links_get_typed_targets_and_the_new_indexes_build(
    links: AsyncIOMotorCollection,
) -> None:
    await links.insert_many(
        [
            _old("todo1", "todo_deliverable", "t1"),
            _old("file1", "session_artifact", "conv-1/reports/q3.html"),
        ]
    )

    assert await migration.migrate(apply=False) == (2, [LIVE_TARGET_UNIQUE_INDEX])
    assert await links.count_documents({"target": {"$exists": True}}) == 0

    assert await migration.migrate(apply=True) == (2, [LIVE_TARGET_UNIQUE_INDEX])
    await indexes.create_short_link_indexes()

    todo = await short_link_repository.get_live_for_target(OWNER, TODO)
    file = await short_link_repository.get_live_for_target(OWNER, FILE)
    assert (todo and todo.slug, file and file.slug) == ("todo1", "file1")
    assert await short_link_repository.live_workspace_files_in(OWNER, "conv-1") == [FILE]
    assert await links.count_documents({"target_type": {"$exists": True}}) == 2
    assert await migration.migrate(apply=True) == (0, [])


async def test_a_link_with_no_old_target_fails_loud(links: AsyncIOMotorCollection) -> None:
    await links.insert_one({"slug": "broken", "user_id": OWNER, "target_type": "briefing"})

    with pytest.raises(ValueError, match="'broken' has no target_type and target_id"):
        await migration.migrate(apply=True)

    assert await links.count_documents({"target_type": "briefing"}) == 1


@pytest.mark.parametrize(
    "old",
    [
        _old("x", "session_artifact", "no-path"),
        _old("x", "session_artifact", "conv-1/"),
        _old("x", "nonsense", "t1"),
    ],
)
def test_an_old_target_that_names_nothing_is_refused(old: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        migration.target_of(old)


async def test_contract_targets_what_the_previous_release_minted_since_then_drops_the_old_fields(
    links: AsyncIOMotorCollection,
) -> None:
    await links.insert_one(_old("todo1", "todo_deliverable", "t1"))
    await migration.migrate(apply=True)
    await indexes.create_short_link_indexes()
    await links.insert_one(_old("file1", "session_artifact", "conv-1/reports/q3.html"))

    assert await migration.contract(apply=False) == 2
    assert await links.count_documents({"target": {"$exists": True}}) == 1

    assert await migration.contract(apply=True) == 2

    file = await short_link_repository.get_live_for_target(OWNER, FILE)
    assert file is not None and file.slug == "file1"
    assert await links.count_documents({"target_type": {"$exists": True}}) == 0
    assert await links.count_documents({"target_id": {"$exists": True}}) == 0
    assert await migration.contract(apply=True) == 0
