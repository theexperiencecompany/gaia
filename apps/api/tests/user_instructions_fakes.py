"""An in-memory user_instructions collection, so the real repository and service run hermetically.

Kept apart from tests/factories.py (imported by every unit conftest) for the same
reason as browser_factories.py: only the suites that touch instructions import it.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytest

_UNIQUE_KEYS = ("user_id", "scope")

Doc = dict[str, Any]


class _FakeCursor:
    def __init__(self, docs: list[Doc]) -> None:
        self._docs = docs

    # async to match the awaited Motor cursor interface the repository relies on.
    async def to_list(self, length: int | None = None) -> list[Doc]:  # NOSONAR python:S7503
        return self._docs if length is None else self._docs[:length]


def _matches(doc: dict[str, Any], flt: dict[str, Any]) -> bool:
    for key, cond in flt.items():
        if isinstance(cond, dict) and "$ne" in cond:
            if doc.get(key) == cond["$ne"]:
                return False
        elif doc.get(key) != cond:
            return False
    return True


def _apply(doc: dict[str, Any], update: dict[str, Any]) -> None:
    doc.update(update.get("$set", {}))
    for key, step in update.get("$inc", {}).items():
        doc[key] = doc.get(key, 0) + step


class FakeCollection:
    """Executes the query semantics the repository relies on, the unique (user_id, scope) index included."""

    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    # async to match the awaited Motor collection interface the repository relies on.
    async def find_one_and_update(  # NOSONAR python:S7503
        self,
        flt: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool = False,
        return_document: object = None,
        array_filters: object = None,
    ) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, flt):
                _apply(doc, update)
                return dict(doc)
        if not upsert:
            return None
        new = {k: v for k, v in flt.items() if not isinstance(v, dict)}
        if any(all(d.get(k) == new.get(k) for k in _UNIQUE_KEYS) for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key error (user_id, scope)")
        _apply(new, update)
        new["_id"] = f"oid-{len(self.docs)}"
        self.docs.append(new)
        return dict(new)

    # async to match the awaited Motor collection interface the repository relies on.
    async def find_one(  # NOSONAR python:S7503
        self,
        flt: dict[str, Any],
        projection: object = None,
        *,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        matching = [doc for doc in self.docs if _matches(doc, flt)]
        for key, direction in reversed(sort or []):
            matching.sort(key=lambda doc: doc[key], reverse=direction < 0)
        return dict(matching[0]) if matching else None

    def find(self, flt: dict[str, Any], projection: object = None) -> _FakeCursor:
        return _FakeCursor([dict(d) for d in self.docs if _matches(d, flt)])


def install_fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    """Back every repository with one in-memory collection and switch the Redis cache off."""
    from app.db.redis import redis_cache

    monkeypatch.setattr(redis_cache, "redis", None)
    fake = FakeCollection()
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: fake)
    return fake


def new_user_id() -> str:
    """Return a real ObjectId, since analytics attributes every save to the user's Mongo id."""
    return str(ObjectId())


# async to match the awaited check_user_has_integration coroutine they replace.
async def always_connected(*_args: object, **_kwargs: object) -> bool:  # NOSONAR python:S7503
    return True


async def never_connected(*_args: object, **_kwargs: object) -> bool:  # NOSONAR python:S7503
    return False
