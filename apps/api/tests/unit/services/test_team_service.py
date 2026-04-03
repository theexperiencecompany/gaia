"""Unit tests for team service operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.constants.cache import DEFAULT_CACHE_TTL, TEAM_CACHE_PREFIX
from app.models.team_models import TeamMember, TeamMemberCreate, TeamMemberUpdate
from app.services.team_service import TEAM_LIST_CACHE_KEY, TeamService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_team_collection():
    with patch("app.services.team_service.team_collection") as mock_col:
        yield mock_col


@pytest.fixture
def mock_redis():
    with (
        patch("app.services.team_service.get_cache", new_callable=AsyncMock) as m_get,
        patch("app.services.team_service.set_cache", new_callable=AsyncMock) as m_set,
        patch(
            "app.services.team_service.delete_cache", new_callable=AsyncMock
        ) as m_del,
    ):
        yield m_get, m_set, m_del


@pytest.fixture
def sample_member_oid():
    return ObjectId()


@pytest.fixture
def sample_member_doc(sample_member_oid):
    return {
        "_id": sample_member_oid,
        "name": "Alice",
        "role": "Engineer",
        "avatar": "https://example.com/alice.jpg",
        "linkedin": "https://linkedin.com/in/alice",
        "twitter": None,
    }


# ---------------------------------------------------------------------------
# get_all_team_members
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllTeamMembers:
    async def test_returns_cached_members(self, mock_team_collection, mock_redis):
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = [
            {"id": "abc", "name": "Alice", "role": "Engineer"},
        ]

        result = await TeamService.get_all_team_members()

        assert len(result) == 1
        assert result[0].name == "Alice"
        mock_team_collection.find.assert_not_called()

    async def test_returns_members_from_db_and_caches(
        self, mock_team_collection, mock_redis, sample_member_doc
    ):
        m_get, m_set, _m_del = mock_redis
        m_get.return_value = None

        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[sample_member_doc])
        mock_team_collection.find.return_value = cursor

        result = await TeamService.get_all_team_members()

        assert len(result) == 1
        assert result[0].name == "Alice"
        m_set.assert_called_once()
        call_args = m_set.call_args
        assert call_args[0][0] == TEAM_LIST_CACHE_KEY
        assert call_args[0][2] == DEFAULT_CACHE_TTL

    async def test_returns_empty_list_when_no_members(
        self, mock_team_collection, mock_redis
    ):
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = None

        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_team_collection.find.return_value = cursor

        result = await TeamService.get_all_team_members()

        assert result == []

    async def test_raises_500_on_db_error(self, mock_team_collection, mock_redis):
        m_get, _m_set, _m_del = mock_redis
        m_get.side_effect = Exception("connection error")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.get_all_team_members()

        assert exc_info.value.status_code == 500
        assert "Failed to retrieve team members" in exc_info.value.detail


# ---------------------------------------------------------------------------
# get_team_member_by_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTeamMemberById:
    async def test_returns_cached_member(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        m_get, _m_set, _m_del = mock_redis
        member_id = str(sample_member_oid)
        m_get.return_value = {
            "id": member_id,
            "name": "Alice",
            "role": "Engineer",
        }

        result = await TeamService.get_team_member_by_id(member_id)

        assert result.name == "Alice"
        mock_team_collection.find_one.assert_not_called()

    async def test_returns_member_from_db_and_caches(
        self, mock_team_collection, mock_redis, sample_member_doc, sample_member_oid
    ):
        m_get, m_set, _m_del = mock_redis
        m_get.return_value = None
        mock_team_collection.find_one = AsyncMock(return_value=sample_member_doc)

        result = await TeamService.get_team_member_by_id(str(sample_member_oid))

        assert result.name == "Alice"
        m_set.assert_called_once()

    async def test_raises_400_on_invalid_id(self, mock_team_collection, mock_redis):
        m_get, _m_set, _m_del = mock_redis

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.get_team_member_by_id("not-a-valid-id")

        assert exc_info.value.status_code == 400
        assert "Invalid team member ID format" in exc_info.value.detail

    async def test_raises_404_when_not_found(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = None
        mock_team_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.get_team_member_by_id(str(sample_member_oid))

        assert exc_info.value.status_code == 404

    async def test_raises_500_on_unexpected_error(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        m_get, _m_set, _m_del = mock_redis
        m_get.return_value = None
        mock_team_collection.find_one = AsyncMock(
            side_effect=RuntimeError("DB exploded")
        )

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.get_team_member_by_id(str(sample_member_oid))

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# create_team_member
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateTeamMember:
    async def test_creates_member_and_invalidates_cache(
        self, mock_team_collection, mock_redis, sample_member_doc, sample_member_oid
    ):
        _m_get, _m_set, m_del = mock_redis
        insert_result = MagicMock(inserted_id=sample_member_oid)
        mock_team_collection.insert_one = AsyncMock(return_value=insert_result)
        mock_team_collection.find_one = AsyncMock(return_value=sample_member_doc)

        create_data = TeamMemberCreate(name="Alice", role="Engineer")
        result = await TeamService.create_team_member(create_data)

        assert result.name == "Alice"
        m_del.assert_called_once_with(TEAM_LIST_CACHE_KEY)

    async def test_raises_500_when_refetch_fails(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        insert_result = MagicMock(inserted_id=sample_member_oid)
        mock_team_collection.insert_one = AsyncMock(return_value=insert_result)
        mock_team_collection.find_one = AsyncMock(return_value=None)

        create_data = TeamMemberCreate(name="Bob", role="Designer")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.create_team_member(create_data)

        assert exc_info.value.status_code == 500
        assert "Failed to retrieve created team member" in exc_info.value.detail

    async def test_raises_500_on_insert_error(self, mock_team_collection, mock_redis):
        _m_get, _m_set, _m_del = mock_redis
        mock_team_collection.insert_one = AsyncMock(
            side_effect=RuntimeError("write error")
        )

        create_data = TeamMemberCreate(name="Charlie", role="PM")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.create_team_member(create_data)

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# update_team_member
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateTeamMember:
    async def test_updates_member_and_invalidates_caches(
        self, mock_team_collection, mock_redis, sample_member_doc, sample_member_oid
    ):
        _m_get, _m_set, m_del = mock_redis
        member_id = str(sample_member_oid)
        update_result = MagicMock(matched_count=1)
        mock_team_collection.update_one = AsyncMock(return_value=update_result)
        mock_team_collection.find_one = AsyncMock(return_value=sample_member_doc)

        update_data = TeamMemberUpdate(name="Alice Updated")
        result = await TeamService.update_team_member(member_id, update_data)

        assert result.name == "Alice"
        # Should invalidate both member cache and list cache
        assert m_del.call_count == 2

    async def test_raises_400_on_invalid_id(self, mock_team_collection, mock_redis):
        _m_get, _m_set, _m_del = mock_redis

        update_data = TeamMemberUpdate(name="X")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.update_team_member("bad-id", update_data)

        assert exc_info.value.status_code == 400

    async def test_raises_400_when_no_fields_to_update(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis

        update_data = TeamMemberUpdate()  # All fields None

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.update_team_member(str(sample_member_oid), update_data)

        assert exc_info.value.status_code == 400
        assert "No valid fields" in exc_info.value.detail

    async def test_raises_404_when_not_matched(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=0)
        mock_team_collection.update_one = AsyncMock(return_value=update_result)

        update_data = TeamMemberUpdate(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.update_team_member(str(sample_member_oid), update_data)

        assert exc_info.value.status_code == 404

    async def test_raises_500_when_refetch_fails(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        update_result = MagicMock(matched_count=1)
        mock_team_collection.update_one = AsyncMock(return_value=update_result)
        mock_team_collection.find_one = AsyncMock(return_value=None)

        update_data = TeamMemberUpdate(name="New Name")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.update_team_member(str(sample_member_oid), update_data)

        assert exc_info.value.status_code == 500

    async def test_raises_500_on_db_error(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        mock_team_collection.update_one = AsyncMock(side_effect=RuntimeError("timeout"))

        update_data = TeamMemberUpdate(role="New Role")

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.update_team_member(str(sample_member_oid), update_data)

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# delete_team_member
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteTeamMember:
    async def test_deletes_member_and_invalidates_caches(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, m_del = mock_redis
        delete_result = MagicMock(deleted_count=1)
        mock_team_collection.delete_one = AsyncMock(return_value=delete_result)

        await TeamService.delete_team_member(str(sample_member_oid))

        assert m_del.call_count == 2

    async def test_raises_400_on_invalid_id(self, mock_team_collection, mock_redis):
        _m_get, _m_set, _m_del = mock_redis

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.delete_team_member("not-valid")

        assert exc_info.value.status_code == 400

    async def test_raises_404_when_not_found(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        delete_result = MagicMock(deleted_count=0)
        mock_team_collection.delete_one = AsyncMock(return_value=delete_result)

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.delete_team_member(str(sample_member_oid))

        assert exc_info.value.status_code == 404

    async def test_raises_500_on_db_error(
        self, mock_team_collection, mock_redis, sample_member_oid
    ):
        _m_get, _m_set, _m_del = mock_redis
        mock_team_collection.delete_one = AsyncMock(
            side_effect=RuntimeError("disk full")
        )

        with pytest.raises(HTTPException) as exc_info:
            await TeamService.delete_team_member(str(sample_member_oid))

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTeamServiceEdgeCases:
    async def test_list_cache_key_uses_correct_prefix(self):
        assert TEAM_LIST_CACHE_KEY == f"{TEAM_CACHE_PREFIX}:list"

    async def test_from_mongo_converts_objectid(self):
        oid = ObjectId()
        doc = {"_id": oid, "name": "Eve", "role": "CTO"}
        member = TeamMember.from_mongo(doc)

        assert member.id == str(oid)
        assert member.name == "Eve"
