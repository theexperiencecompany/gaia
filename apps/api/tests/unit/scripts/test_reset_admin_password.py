"""The admin password reset keeps the administrator's account and data, and logs out every session."""

from typing import Any

import bcrypt
from bson import ObjectId
import pytest

from app.models.auth_models import ADMIN_CREDENTIAL_SLOT
from app.scripts.reset_admin_password import reset_admin_credential

ADMIN_ID = str(ObjectId())
MEMBER_ID = str(ObjectId())


class FakeCredentials:
    """The two pymongo collection calls the reset makes, over in-memory rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find_one(self, filter_: dict[str, Any]) -> dict[str, Any] | None:
        return next((r for r in self.rows if all(r.get(k) == v for k, v in filter_.items())), None)

    def update_one(self, filter_: dict[str, Any], update: dict[str, dict[str, Any]]) -> None:
        row = self.find_one(filter_)
        assert row is not None
        row.update(update.get("$set", {}))
        for key, step in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + step


@pytest.fixture
def credentials() -> FakeCredentials:
    return FakeCredentials(
        [
            {
                "_id": ObjectId(),
                "user_id": ADMIN_ID,
                "slot": ADMIN_CREDENTIAL_SLOT,
                "password_hash": "old-hash",
                "token_version": 3,
            },
            {
                "_id": ObjectId(),
                "user_id": MEMBER_ID,
                "password_hash": "member-hash",
                "token_version": 0,
            },
        ]
    )


def test_the_admin_keeps_their_account_and_signs_in_with_the_new_password(
    credentials: FakeCredentials,
) -> None:
    password = reset_admin_credential(credentials)

    assert password is not None
    assert len(password) == 24  # 18 random bytes, url-safe base64
    admin = credentials.find_one({"slot": ADMIN_CREDENTIAL_SLOT})
    assert admin is not None and admin["user_id"] == ADMIN_ID
    assert bcrypt.checkpw(password.encode(), admin["password_hash"].encode())


def test_every_existing_admin_session_is_revoked(credentials: FakeCredentials) -> None:
    reset_admin_credential(credentials)

    admin = credentials.find_one({"slot": ADMIN_CREDENTIAL_SLOT})
    assert admin is not None and admin["token_version"] == 4


def test_members_are_untouched(credentials: FakeCredentials) -> None:
    reset_admin_credential(credentials)

    member = credentials.find_one({"user_id": MEMBER_ID})
    assert member is not None
    assert (member["password_hash"], member["token_version"]) == ("member-hash", 0)


def test_without_an_admin_there_is_nothing_to_reset() -> None:
    assert reset_admin_credential(FakeCredentials([])) is None
