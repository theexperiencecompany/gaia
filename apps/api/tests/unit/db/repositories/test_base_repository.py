"""Hermetic unit tests for _BaseRepository.__init_subclass__ validation.

The base rejects a concrete subclass whose required ClassVars are missing or
whose models are not pydantic BaseModel subclasses — at class-definition time,
so a misconfigured repository fails at import, not on its first query. These
tests pin that contract and the exception it raises; the mutation gate needs
them because the raise sites are the PR's changed lines.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
import inspect
from typing import Any, Protocol
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel
from pymongo.errors import AutoReconnect, BulkWriteError, DuplicateKeyError
import pytest

from app.db.repositories.base import MongoDocument, _BaseRepository
from app.db.repositories.errors import AlreadyExistsError, RepositoryError
from app.utils.errors import RepositoryMisconfiguredError

_BASE = "app.db.repositories.base"


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
    return type("ThingRepository", (_BaseRepository,), classvars)


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


@pytest.mark.parametrize(
    ("overrides", "doc_id", "valid"),
    [
        ({"uses_object_id": True}, "6812f0b3c9a14e2b7d5a91cc", True),
        ({"uses_object_id": True}, "user-1", False),
        ({"uses_object_id": True, "identity_field": "conversation_id"}, "user-1", True),
        ({"uses_object_id": False}, "user-1", True),
        ({"uses_object_id": False}, "", False),
    ],
    ids=["object-id", "not-an-object-id", "business-key", "string-id", "empty"],
)
def test_an_id_is_valid_by_the_collections_own_identity(
    overrides: dict[str, Any], doc_id: str, valid: bool
) -> None:
    assert _concrete(**overrides)().is_valid_id(doc_id) is valid


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


async def test_find_one_asks_its_own_collection_with_the_filter_and_order() -> None:
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    with patch(
        "app.db.repositories.base.get_async_collection", return_value=collection
    ) as get_collection:
        found = await _concrete()()._find_one({"name": "x"}, sort=[("name", -1)])

    assert found is None
    get_collection.assert_called_once_with("things")
    collection.find_one.assert_awaited_once_with({"name": "x"}, sort=[("name", -1)])


class _Things(Protocol):
    async def get_twice(self, name: str) -> _Doc | None: ...
    async def get_by_name(self, name: str) -> _Doc | None: ...
    async def create_or_false(self, doc: _Doc) -> bool: ...
    async def create(self, doc: _Doc) -> _Doc: ...


def _things_repository() -> _Things:
    """Define the repository inside the test, so class creation runs under the active mutant."""

    class ThingsRepository(_BaseRepository[_Doc, _Update]):
        collection_name = "things"
        document_model = _Doc
        update_model = _Update
        uses_object_id = False

        async def get_twice(self, name: str) -> _Doc | None:
            return await self.get_by_name(name=name) or await self.get_by_name(name=name)

        async def get_by_name(self, name: str) -> _Doc | None:
            return await self._find_one({"name": name})

        async def create_or_false(self, doc: _Doc) -> bool:
            try:
                await self.create(doc)
            except DuplicateKeyError:
                return False
            return True

    return ThingsRepository()


def _failing(operation: str, error: Exception) -> MagicMock:
    collection = MagicMock()
    setattr(collection, operation, AsyncMock(side_effect=error))
    return collection


async def test_a_driver_failure_leaves_a_public_call_as_a_repository_error() -> None:
    outage = AutoReconnect("primary stepped down")
    with (
        patch(f"{_BASE}.get_async_collection", return_value=_failing("find_one", outage)),
        pytest.raises(RepositoryError) as raised,
    ):
        await _things_repository().get_twice("x")

    assert type(raised.value) is RepositoryError
    assert raised.value.__cause__ is outage
    assert str(raised.value) == "AutoReconnect: primary stepped down"


async def test_a_duplicate_key_leaves_a_public_call_as_already_exists() -> None:
    duplicate = DuplicateKeyError("E11000")
    with (
        patch(f"{_BASE}.get_async_collection", return_value=_failing("insert_one", duplicate)),
        pytest.raises(AlreadyExistsError) as raised,
    ):
        await _things_repository().create(_Doc(id="a", name="a"))

    assert raised.value.__cause__ is duplicate
    assert str(raised.value) == "DuplicateKeyError: E11000"


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        ({"writeErrors": [{"code": 11000}]}, AlreadyExistsError),
        ({"writeErrors": [{"code": 121}]}, RepositoryError),
        ({}, RepositoryError),
    ],
    ids=["duplicate", "validation", "no_write_errors"],
)
async def test_a_bulk_write_failure_is_already_exists_only_for_a_duplicate_key(
    details: dict[str, object], expected: type[RepositoryError]
) -> None:
    refused = BulkWriteError(details)
    with (
        patch(f"{_BASE}.get_async_collection", return_value=_failing("insert_one", refused)),
        pytest.raises(RepositoryError) as raised,
    ):
        await _things_repository().create(_Doc(id="a", name="a"))

    assert type(raised.value) is expected


async def test_a_repository_body_still_catches_the_driver_error_of_its_own_nested_call() -> None:
    collection = _failing("insert_one", DuplicateKeyError("E11000"))
    with patch(f"{_BASE}.get_async_collection", return_value=collection):
        assert await _things_repository().create_or_false(_Doc(id="a", name="a")) is False


async def test_a_driver_failure_after_a_translated_call_translates_again() -> None:
    """The inside-a-call marker is reset when a call ends, so the next outermost call translates."""
    repo = _things_repository()
    collection = _failing("find_one", AutoReconnect("down"))
    with patch(f"{_BASE}.get_async_collection", return_value=collection):
        for _ in range(2):
            with pytest.raises(RepositoryError):
                await repo.get_twice("x")


async def test_a_wrapped_method_receives_its_keyword_arguments() -> None:
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={"_id": "a", "name": "found"})
    with patch(f"{_BASE}.get_async_collection", return_value=collection):
        found = await _things_repository().get_twice(name="found")

    assert found == _Doc(id="a", name="found")
    collection.find_one.assert_awaited_once_with({"name": "found"}, sort=None)


async def test_a_private_primitive_called_directly_lets_the_driver_error_through() -> None:
    outage = AutoReconnect("down")
    with (
        patch(f"{_BASE}.get_async_collection", return_value=_failing("find_one", outage)),
        pytest.raises(AutoReconnect),
    ):
        await _concrete()()._find_one({"name": "x"})


def test_an_inherited_public_method_is_wrapped_once() -> None:
    parent = type(_things_repository())
    child = type("ChildRepository", (parent,), {})
    wrapped = inspect.getattr_static(parent, "get_twice")

    assert "get_twice" not in vars(child)
    assert inspect.getattr_static(child, "get_twice") is wrapped
    assert wrapped.__wrapped__.__name__ == "get_twice"


async def test_the_wide_event_names_the_driver_error_behind_the_repository_error() -> None:
    recorded: list[dict[str, object]] = []
    with (
        patch(
            f"{_BASE}.get_async_collection", return_value=_failing("find_one", AutoReconnect("x"))
        ),
        patch(f"{_BASE}.log.set", lambda **fields: recorded.append(fields)),
        pytest.raises(RepositoryError),
    ):
        await _things_repository().get_twice("x")

    assert recorded == [
        {
            "repository_error": {
                "operation": "ThingsRepository.get_twice",
                "error_type": "RepositoryError",
                "cause_type": "AutoReconnect",
            }
        }
    ]


def test_a_public_async_generator_is_refused_at_class_creation() -> None:
    async def stream(self: object) -> AsyncIterator[_Doc]:
        yield _Doc()

    with pytest.raises(RepositoryMisconfiguredError) as refused:
        _concrete(stream=stream)

    assert refused.value.message == "ThingRepository.stream would escape driver-error translation"
    assert (
        refused.value.why
        == "only public async instance methods are wrapped to raise RepositoryError"
    )
    assert refused.value.fix == (
        "make stream an async instance method returning a list, or prefix it with _"
    )


def test_a_public_static_coroutine_is_refused_at_class_creation() -> None:
    async def lookup() -> None:
        return None

    with pytest.raises(RepositoryMisconfiguredError, match="lookup"):
        _concrete(lookup=staticmethod(lookup))


def test_a_public_sync_method_and_a_private_coroutine_are_left_unwrapped() -> None:
    def label(self: object) -> str:
        return "x"

    async def _helper(self: object) -> None:
        return None

    repo_class = _concrete(label=label, _helper=_helper)

    assert repo_class.__dict__["label"] is label
    assert repo_class.__dict__["_helper"] is _helper
