"""Hermetic unit tests for ``_BaseRepository.__init_subclass__`` validation.

The base rejects a concrete subclass whose required ClassVars are missing or
whose models are not pydantic BaseModel subclasses — at class-definition time,
so a misconfigured repository fails at import, not on its first query. These
tests pin that contract and the exception it raises; the mutation gate needs
them because the raise sites are the PR's changed lines.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from pydantic import BaseModel
import pytest

from app.db.repositories.base import MongoDocument, _BaseRepository
from app.utils.errors import RepositoryMisconfiguredError


class _Doc(MongoDocument):
    name: str = ""


class _Update(BaseModel):
    name: str | None = None


def _concrete(**overrides: Any) -> type[_BaseRepository]:
    """A minimally valid concrete repository, with ClassVars replaced by overrides."""
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


_VALID_OBJECT_ID = "507f1f77bcf86cd799439011"


@pytest.mark.regression
@pytest.mark.parametrize("malformed", ["", "not-an-objectid", "z" * 24])
def test_object_id_repo_matches_malformed_id_as_plain_string(malformed: str) -> None:
    """A malformed id must not raise ``bson.InvalidId`` — it returns the plain
    string so the identity filter misses and get/update/delete read as
    not-found. Regression for the empty-``todo_id`` agent-turn crash."""
    repo = _concrete(uses_object_id=True)()

    value = repo._id_value(malformed)

    assert value == malformed  # unwrapped: an ObjectId _id never equals a string
    assert repo._identity_filter(malformed) == {"_id": malformed}


def test_object_id_repo_still_wraps_a_valid_id() -> None:
    repo = _concrete(uses_object_id=True)()

    assert repo._id_value(_VALID_OBJECT_ID) == ObjectId(_VALID_OBJECT_ID)


def test_business_key_repo_leaves_any_id_as_a_plain_string() -> None:
    repo = _concrete(uses_object_id=False)()

    assert repo._id_value("anything") == "anything"
