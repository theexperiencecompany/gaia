"""The email-lowercasing migration against a real users collection."""

import pytest
from scripts.lowercase_user_emails import apply_plan, build_plan, read_stored_emails

from app.db.repositories.users import user_repository
from scripts import lowercase_user_emails


@pytest.fixture
async def users(mongo_db, monkeypatch):
    monkeypatch.setattr(lowercase_user_emails, "get_async_collection", lambda name: mongo_db[name])
    collection = mongo_db["users"]
    await collection.delete_many({})
    yield collection
    await collection.delete_many({})


async def test_apply_lowercases_safe_rows_and_leaves_duplicates(users) -> None:
    lone = await users.insert_one({"email": "Lone@X.com", "name": "A"})
    await users.insert_many(
        [{"email": "Twin@X.com", "name": "B"}, {"email": "twin@x.com", "name": "C"}]
    )

    plan = build_plan(await read_stored_emails())
    written = await apply_plan(plan)

    assert written == 1
    stored = sorted([doc["email"] async for doc in users.find({}, {"email": 1})])
    assert stored == ["Twin@X.com", "lone@x.com", "twin@x.com"]
    found = await user_repository.get_by_email("Lone@X.com")
    assert found is not None
    assert found.id == str(lone.inserted_id)
