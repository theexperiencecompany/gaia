"""Note writes on the todos repository: stamped unless told not to, cached under their owner."""

from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoUpdate

TODO_ID = "66f838cc8829054e5f10e401"


async def _replace_canvas(**touch: bool) -> tuple[dict[str, object], AsyncMock, AsyncMock]:
    collection = MagicMock()
    collection.find_one_and_update = AsyncMock(
        return_value={"_id": ObjectId(TODO_ID), "user_id": "u1", "title": "t"}
    )
    with (
        patch("app.db.repositories.base.get_async_collection", return_value=collection),
        patch.object(todo_repository, "_cache_store", AsyncMock()) as store,
        patch.object(todo_repository, "_invalidate", AsyncMock()) as invalidate,
    ):
        await todo_repository.replace_note_fields(
            TODO_ID, "u1", update=TodoUpdate(canvas_content="v2"), expected_updated_at=None, **touch
        )
    (_filter, operations), _ = collection.find_one_and_update.await_args
    return operations["$set"], store, invalidate


async def test_a_note_write_stamps_updated_at_by_default() -> None:
    written, _store, _invalidate = await _replace_canvas()

    assert written["canvas_content"] == "v2"
    assert "updated_at" in written


async def test_an_untouched_note_write_keeps_updated_at() -> None:
    written, _store, _invalidate = await _replace_canvas(touch=False)

    assert written == {"canvas_content": "v2"}


async def test_a_note_write_refreshes_its_owners_cache() -> None:
    _written, store, invalidate = await _replace_canvas()

    assert store.await_args.args[0] == "u1"
    invalidate.assert_awaited_once_with("u1")
