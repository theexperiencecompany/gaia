"""Contract + finder tests for NotesRepository against real Mongo + Redis."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.db.repositories.notes import NotesRepository
from app.models.notes_models import NoteDocument, NoteUpdate
from tests.contracts.base_contract import UserScopedRepositoryContract


@pytest.fixture
def repo(raw_collection) -> NotesRepository:
    return NotesRepository()


@pytest.fixture
def make_doc() -> Callable[..., NoteDocument]:
    def _make(**overrides: object) -> NoteDocument:
        return NoteDocument.model_validate(
            {"user_id": "user-1", "content": "<p>hi</p>", "plaintext": "hi", **overrides}
        )

    return _make


@pytest.fixture
def make_update() -> Callable[..., NoteUpdate]:
    def _make(**fields: object) -> NoteUpdate:
        return NoteUpdate.model_validate(fields or {"content": "<p>edited</p>"})

    return _make


class TestNotesRepository(UserScopedRepositoryContract):
    """Runs the full user-scoped contract against the real notes repository."""

    async def list_via_cache(self, repo, user_id: str) -> list:
        return await repo.list_notes(user_id=user_id)

    async def test_list_notes_returns_only_the_users_notes(self, repo, make_doc):
        await repo.create(make_doc(user_id="owner", plaintext="a"))
        await repo.create(make_doc(user_id="owner", plaintext="b"))
        await repo.create(make_doc(user_id="other", plaintext="c"))
        notes = await repo.list_notes(user_id="owner")
        assert sorted(note.plaintext for note in notes) == ["a", "b"]
        assert all(note.user_id == "owner" for note in notes)

    async def test_update_only_touches_set_fields(self, repo, make_doc):
        created = await repo.create(make_doc(content="<p>orig</p>", plaintext="orig"))
        updated = await repo.update(
            created.id, user_id=created.user_id, update=NoteUpdate(plaintext="new")
        )
        assert updated is not None
        assert updated.plaintext == "new"
        assert updated.content == "<p>orig</p>"  # untouched

    async def test_search_by_plaintext(self, repo, make_doc):
        created = await repo.create(
            make_doc(user_id="searcher", plaintext="the quarterly budget report")
        )
        await repo.create(make_doc(user_id="searcher", plaintext="lunch plans"))
        await repo.create(make_doc(user_id="other", plaintext="budget too"))
        hits = await repo.search_by_plaintext("searcher", pattern="budget")
        assert [h.plaintext for h in hits] == ["the quarterly budget report"]
        assert hits[0].id == created.id  # the stringified _id, user-isolated


class TestNotesFindByIds:
    async def test_find_by_ids_is_scoped(self, repo, make_doc):
        a = await repo.create(make_doc(user_id="u1"))
        b = await repo.create(make_doc(user_id="u1"))
        await repo.create(make_doc(user_id="u2"))
        found = await repo.find_by_ids("u1", [a.id, b.id])
        assert {n.id for n in found} == {a.id, b.id}
        assert await repo.find_by_ids("u1", []) == []
