"""Hermetic unit tests for _BaseRepository.__init_subclass__ validation.

The base rejects a concrete subclass whose required ClassVars are missing or
whose models are not pydantic BaseModel subclasses — at class-definition time,
so a misconfigured repository fails at import, not on its first query. These
tests pin that contract and the exception it raises; the mutation gate needs
them because the raise sites are the PR's changed lines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel
import pytest

from app.db.repositories.base import MongoDocument, _BaseRepository
from app.utils.errors import RepositoryMisconfiguredError


class _Doc(MongoDocument):
    name: str = ""


class _Update(BaseModel):
    name: str | None = None


class _StampedDoc(MongoDocument):
    name: str = ""
    updated_at: datetime | None = None


def _concrete(**overrides: Any) -> type[_BaseRepository]:
    """Build a minimally valid concrete repository, with ClassVars replaced by overrides."""
    classvars: dict[str, Any] = {
        "collection_name": "things",
        "document_model": _Doc,
        "update_model": _Update,
        "uses_object_id": False,
    }
    classvars.update(overrides)
    return type("ThingRepository", (_BaseRepository,), classvars)  # type: ignore[return-value]  # test builds an untyped dynamic subclass


def test_a_complete_concrete_repository_is_accepted() -> None:
    repo = _concrete()

    assert repo.collection_name == "things"


@pytest.mark.parametrize(
    "missing",
    ["collection_name", "document_model", "update_model", "uses_object_id"],
)
def test_a_missing_classvar_names_it_and_raises(missing: str) -> None:
    with pytest.raises(RepositoryMisconfiguredError) as exc_info:
        _concrete(**{missing: None})

    message = str(exc_info.value)
    assert missing in message


def test_a_non_pydantic_document_model_raises() -> None:
    class NotAModel:
        pass

    with pytest.raises(RepositoryMisconfiguredError) as exc_info:
        _concrete(document_model=NotAModel)

    assert "document_model" in str(exc_info.value)


def test_an_abstract_subclass_needs_no_classvars() -> None:
    class AbstractRepo(_BaseRepository, abstract=True):
        pass


def test_a_filter_naming_one_id_reports_it_as_the_targeted_doc() -> None:
    """_apply_raw_update evicts this id when the write matches nothing."""
    repo = _concrete()()

    assert repo._filter_doc_id({"_id": "abc", "user_id": "u1"}) == "abc"


def test_a_filter_that_names_no_id_targets_no_doc() -> None:
    repo = _concrete()()

    assert repo._filter_doc_id({"user_id": "u1"}) is None


def test_an_operator_valued_id_targets_no_single_doc() -> None:
    """An operator-valued id matches a set, so stringifying it would evict a key that exists for nobody and leave real entities stale."""
    repo = _concrete()()

    assert repo._filter_doc_id({"_id": {"$in": ["a", "b"]}}) is None
    assert repo._filter_doc_id({"_id": {"$ne": "a"}}) is None


async def _set_written(repo: _BaseRepository, *, touch: bool = True) -> dict[str, object]:
    collection = MagicMock()
    collection.find_one_and_update = AsyncMock(return_value=None)
    with patch("app.db.repositories.base.get_async_collection", return_value=collection):
        await repo._apply_update("abc", "u1", {}, _Update(name="x"), touch=touch)
    (_filter, operations), _ = collection.find_one_and_update.await_args
    return operations["$set"]


async def test_an_update_stamps_updated_at() -> None:
    written = await _set_written(_concrete(document_model=_StampedDoc)())

    assert written["name"] == "x"
    assert isinstance(written["updated_at"], datetime)


async def test_an_untouched_update_keeps_updated_at() -> None:
    assert await _set_written(_concrete(document_model=_StampedDoc)(), touch=False) == {"name": "x"}


async def test_a_repository_that_stamps_nothing_writes_no_updated_at() -> None:
    repo = _concrete(document_model=_StampedDoc, auto_stamp_timestamps=False)()

    assert await _set_written(repo) == {"name": "x"}


async def test_a_document_without_updated_at_is_not_stamped() -> None:
    assert await _set_written(_concrete()()) == {"name": "x"}
