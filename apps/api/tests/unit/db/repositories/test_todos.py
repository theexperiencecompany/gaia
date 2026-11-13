"""Todos repository writes: notes stamped unless told not to and cached under their owner, gate skips kept."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.constants.trigger_gates import GATE_RECENT_SKIPS_KEPT
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoUpdate
from app.models.trigger_gate_models import GateSkipRecord

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


async def test_a_skip_is_kept_only_on_the_users_gated_watch_without_reading_it_back() -> None:
    skip = GateSkipRecord(event="Substack · Weekly digest", at=datetime(2026, 11, 5, 9, tzinfo=UTC))
    with patch.object(todo_repository, "_apply_raw_update", AsyncMock(return_value=None)) as raw:
        await todo_repository.remember_subscription_gate_skip(
            user_id="u1", subscription_id="watch-1", skip=skip
        )

    raw.assert_awaited_once_with(
        {"user_id": "u1"},
        {
            "$push": {
                "trigger_subscriptions.$[watch].gate.recent_skips": {
                    "$each": [skip.model_dump()],
                    "$slice": -GATE_RECENT_SKIPS_KEPT,
                }
            },
            "$inc": {"trigger_subscriptions.$[watch].gate.skipped_count": 1},
        },
        scope="u1",
        extra_filter={
            "trigger_subscriptions": {"$elemMatch": {"id": "watch-1", "gate": {"$ne": None}}}
        },
        array_filters=[{"watch.id": "watch-1"}],
        return_document=False,
    )


async def test_a_reopen_write_is_filtered_to_the_users_todo_still_completed() -> None:
    collection = MagicMock()
    collection.find_one_and_update = AsyncMock(
        return_value={"_id": ObjectId(TODO_ID), "user_id": "u1", "title": "t"}
    )
    with (
        patch("app.db.repositories.base.get_async_collection", return_value=collection),
        patch.object(todo_repository, "_cache_store", AsyncMock()) as store,
        patch.object(todo_repository, "_invalidate", AsyncMock()) as invalidate,
    ):
        reopened = await todo_repository.update_if_completed(
            TODO_ID, "u1", update=TodoUpdate(completed=False)
        )

    (query, operations), _ = collection.find_one_and_update.await_args
    assert query == {"_id": ObjectId(TODO_ID), "user_id": "u1", "completed": True}
    assert operations["$set"]["completed"] is False
    assert reopened is not None and reopened.id == TODO_ID
    # The reopened todo is refreshed in its owner's cache, not a scope-less one.
    assert store.await_args.args[0] == "u1"
    invalidate.assert_awaited_once_with("u1")


async def test_a_reopen_write_that_matches_nothing_returns_none() -> None:
    collection = MagicMock()
    collection.find_one_and_update = AsyncMock(return_value=None)
    with patch("app.db.repositories.base.get_async_collection", return_value=collection):
        reopened = await todo_repository.update_if_completed(
            TODO_ID, "u1", update=TodoUpdate(completed=False)
        )

    assert reopened is None
