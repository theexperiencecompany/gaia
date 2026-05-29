"""Unit tests for DeviceTokenService.

UNIT: app/services/device_token_service.py :: DeviceTokenService + get_device_token_service

register_device_token
  EXPECTED: upsert a doc keyed on {token}; $set the live fields, $setOnInsert created_at;
            log "registered" on insert / "updated" on match; return True, or False on DB error.
  MECHANISM: collection.update_one(filter, {"$set": {...}, "$setOnInsert": {"created_at": now}},
             upsert=True); branch on result.upserted_id.
  MUST-CATCH: filter is exactly {"token": token}; $set carries user_id/platform.value/device_id/
              is_active=True/updated_at; $setOnInsert has created_at; upsert=True;
              upserted_id truthy -> "registered" action, falsy -> "updated" action; DB error -> False.

get_user_device_count
  EXPECTED: return collection.count_documents({"user_id": user_id}); 0 on DB error.
  MUST-CATCH: query is {"user_id": user_id}; real count returned; error -> 0.

verify_token_ownership
  EXPECTED: True iff find_one({"token", "user_id"}) returns a doc; False on miss or DB error.
  MUST-CATCH: query carries both token and user_id; doc present -> True; None -> False; error -> False.

unregister_device_token
  EXPECTED: delete_one({"token", "user_id"}); True if deleted_count>0 else False; False on error.
            Token masked in log: long (>24) -> first20...last4, short -> "***".
  MUST-CATCH: query carries both keys; deleted_count>0 -> True else False; error -> False;
              masking boundary at len 24, [:20] and [-4:] slices.

unregister_user_devices
  EXPECTED: delete_many({"user_id": user_id}); return deleted_count; 0 on error.
  MUST-CATCH: query is {"user_id": user_id}; real deleted_count returned; error -> 0.

get_user_tokens
  EXPECTED: find(query) where query has is_active=True only when active_only; collect doc["token"]; [] on error.
  MUST-CATCH: active_only adds is_active=True, otherwise absent; tokens extracted in order; error -> [].

deactivate_invalid_token
  EXPECTED: update_one({"token"}, {"$set": {is_active=False, updated_at}}); True; False on error.
  MUST-CATCH: filter is {"token": token}; $set.is_active is False; updated_at present; error -> False;
              masking boundary at len 24, [:20] and [-4:] slices.

get_device_token_service
  EXPECTED: lazily build + cache a singleton; first call inits MongoDB, later calls reuse it.
  MUST-CATCH: None sentinel -> init_mongodb called once + instance built; cached -> no re-init, same object.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.device_token_models import PlatformType
from app.services.device_token_service import DeviceTokenService

TOKEN = "ExponentPushToken[abc]"
LONG_TOKEN = "ExponentPushToken[abcdefghij123456789]"  # 39 chars (>24)
SHORT_TOKEN = "short_token_24_chars_xyz"  # exactly 24 chars (not >24)
BOUNDARY_TOKEN = "ExponentPushTokenABCDE123"  # exactly 25 chars (the > 24 boundary)


class _AsyncIterator:
    """Real async iterator over a list, matching Motor cursor async-for semantics."""

    def __init__(self, items: list):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.fixture
def mock_collection():
    return AsyncMock()


@pytest.fixture
def service(mock_collection):
    mock_mongodb = MagicMock()
    mock_mongodb.database.get_collection.return_value = mock_collection
    svc = DeviceTokenService(mock_mongodb)
    # __init__ pulls the "device_tokens" collection; assert it wired the right one.
    mock_mongodb.database.get_collection.assert_called_once_with("device_tokens")
    assert svc.collection is mock_collection
    return svc


@pytest.fixture
def captured_log():
    """Patch the module-level wide-events log so info/set/warning calls are observable."""
    with patch("app.services.device_token_service.log") as mock_log:
        yield mock_log


# ---------------------------------------------------------------------------
# register_device_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterDeviceToken:
    async def test_new_token_upsert_payload_and_registered_action(
        self, service, mock_collection, captured_log
    ):
        mock_collection.update_one = AsyncMock(return_value=MagicMock(upserted_id="new_id"))

        result = await service.register_device_token(
            "user1", TOKEN, PlatformType.IOS, device_id="device123"
        )

        assert result is True
        mock_collection.update_one.assert_awaited_once()
        args, kwargs = mock_collection.update_one.call_args
        # filter keyed solely on the token (race-safe upsert)
        assert args[0] == {"token": TOKEN}
        update = args[1]
        set_data = update["$set"]
        assert set_data["user_id"] == "user1"
        assert set_data["platform"] == "ios"  # platform.value, not the enum
        assert set_data["device_id"] == "device123"
        assert set_data["is_active"] is True
        # $setOnInsert must carry created_at and share the same timestamp object as updated_at
        assert "created_at" in update["$setOnInsert"]
        assert update["$setOnInsert"]["created_at"] == set_data["updated_at"]
        assert kwargs["upsert"] is True
        # upserted_id truthy -> "registered" action recorded in the wide event
        set_calls = [c.kwargs["device_token"] for c in captured_log.set.call_args_list]
        assert {"user_id": "user1", "platform": "ios", "action": "registered"} in set_calls

    async def test_existing_token_records_updated_action(
        self, service, mock_collection, captured_log
    ):
        mock_collection.update_one = AsyncMock(return_value=MagicMock(upserted_id=None))

        result = await service.register_device_token("user1", TOKEN, PlatformType.ANDROID)

        assert result is True
        # falsy upserted_id -> "updated" branch, platform.value carried through
        set_calls = [c.kwargs["device_token"] for c in captured_log.set.call_args_list]
        assert {"user_id": "user1", "platform": "android", "action": "updated"} in set_calls
        assert {"user_id": "user1", "platform": "android", "action": "registered"} not in set_calls

    async def test_device_id_defaults_to_none(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(return_value=MagicMock(upserted_id="x"))

        await service.register_device_token("user1", TOKEN, PlatformType.IOS)

        assert mock_collection.update_one.call_args[0][1]["$set"]["device_id"] is None

    async def test_db_error_returns_false(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.register_device_token("user1", TOKEN, PlatformType.IOS)

        assert result is False


# ---------------------------------------------------------------------------
# get_user_device_count
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserDeviceCount:
    async def test_returns_real_count_with_correct_query(self, service, mock_collection):
        mock_collection.count_documents = AsyncMock(return_value=3)

        result = await service.get_user_device_count("user1")

        assert result == 3
        mock_collection.count_documents.assert_awaited_once_with({"user_id": "user1"})

    async def test_returns_zero_on_error(self, service, mock_collection):
        mock_collection.count_documents = AsyncMock(side_effect=Exception("DB error"))

        result = await service.get_user_device_count("user1")

        assert result == 0


# ---------------------------------------------------------------------------
# verify_token_ownership
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyTokenOwnership:
    async def test_true_when_doc_found_with_token_and_user_query(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(return_value={"token": TOKEN, "user_id": "user1"})

        result = await service.verify_token_ownership(TOKEN, "user1")

        assert result is True
        mock_collection.find_one.assert_awaited_once_with({"token": TOKEN, "user_id": "user1"})

    async def test_false_when_not_found(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(return_value=None)

        result = await service.verify_token_ownership(TOKEN, "user1")

        assert result is False

    async def test_false_on_error(self, service, mock_collection):
        mock_collection.find_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.verify_token_ownership(TOKEN, "user1")

        assert result is False


# ---------------------------------------------------------------------------
# unregister_device_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnregisterDeviceToken:
    async def test_success_deletes_by_token_and_user(self, service, mock_collection):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        result = await service.unregister_device_token(TOKEN, "user1")

        assert result is True
        mock_collection.delete_one.assert_awaited_once_with({"token": TOKEN, "user_id": "user1"})

    async def test_not_found_returns_false_and_warns(self, service, mock_collection, captured_log):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await service.unregister_device_token(TOKEN, "user1")

        assert result is False
        captured_log.warning.assert_called_once()

    async def test_error_returns_false(self, service, mock_collection):
        mock_collection.delete_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.unregister_device_token(TOKEN, "user1")

        assert result is False

    async def test_long_token_masked_as_first20_dots_last4(
        self, service, mock_collection, captured_log
    ):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        await service.unregister_device_token(LONG_TOKEN, "user1")

        # masking contract: first 20 chars + "..." + last 4 chars
        expected_mask = f"{LONG_TOKEN[:20]}...{LONG_TOKEN[-4:]}"
        assert expected_mask == "ExponentPushToken[ab...789]"
        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert expected_mask in logged
        # full token must never be logged in clear
        assert LONG_TOKEN not in logged

    async def test_short_token_masked_as_stars(self, service, mock_collection, captured_log):
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        # 24 chars: NOT > 24, so fully masked
        assert len(SHORT_TOKEN) == 24
        await service.unregister_device_token(SHORT_TOKEN, "user1")

        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert "***" in logged
        assert SHORT_TOKEN not in logged

    async def test_boundary_25_char_token_is_partially_masked(
        self, service, mock_collection, captured_log
    ):
        # 25 chars: > 24 is True, so partial mask (pins the boundary at exactly 24, not 25)
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        assert len(BOUNDARY_TOKEN) == 25
        await service.unregister_device_token(BOUNDARY_TOKEN, "user1")

        expected_mask = f"{BOUNDARY_TOKEN[:20]}...{BOUNDARY_TOKEN[-4:]}"
        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert expected_mask in logged
        assert "***" not in logged


# ---------------------------------------------------------------------------
# unregister_user_devices
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnregisterUserDevices:
    async def test_returns_deleted_count_with_correct_query(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=3))

        result = await service.unregister_user_devices("user1")

        assert result == 3
        mock_collection.delete_many.assert_awaited_once_with({"user_id": "user1"})

    async def test_returns_zero_when_none_deleted(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))

        result = await service.unregister_user_devices("user1")

        assert result == 0

    async def test_returns_zero_on_error(self, service, mock_collection):
        mock_collection.delete_many = AsyncMock(side_effect=Exception("DB error"))

        result = await service.unregister_user_devices("user1")

        assert result == 0


# ---------------------------------------------------------------------------
# get_user_tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUserTokens:
    async def test_active_only_adds_is_active_filter_and_extracts_tokens(
        self, service, mock_collection
    ):
        mock_collection.find = MagicMock(
            return_value=_AsyncIterator([{"token": "tok1"}, {"token": "tok2"}])
        )

        result = await service.get_user_tokens("user1")

        assert result == ["tok1", "tok2"]
        mock_collection.find.assert_called_once_with({"user_id": "user1", "is_active": True})

    async def test_not_active_only_omits_is_active_filter(self, service, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncIterator([{"token": "tok1"}]))

        result = await service.get_user_tokens("user1", active_only=False)

        assert result == ["tok1"]
        mock_collection.find.assert_called_once_with({"user_id": "user1"})

    async def test_returns_empty_on_error(self, service, mock_collection):
        mock_collection.find = MagicMock(side_effect=Exception("DB error"))

        result = await service.get_user_tokens("user1")

        assert result == []

    async def test_returns_empty_when_no_tokens(self, service, mock_collection):
        mock_collection.find = MagicMock(return_value=_AsyncIterator([]))

        result = await service.get_user_tokens("user1")

        assert result == []


# ---------------------------------------------------------------------------
# deactivate_invalid_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivateInvalidToken:
    async def test_sets_is_active_false_for_token(self, service, mock_collection):
        mock_collection.update_one = AsyncMock()

        result = await service.deactivate_invalid_token(TOKEN)

        assert result is True
        args = mock_collection.update_one.call_args[0]
        assert args[0] == {"token": TOKEN}
        set_data = args[1]["$set"]
        assert set_data["is_active"] is False
        assert "updated_at" in set_data

    async def test_returns_false_on_error(self, service, mock_collection):
        mock_collection.update_one = AsyncMock(side_effect=Exception("DB error"))

        result = await service.deactivate_invalid_token(TOKEN)

        assert result is False

    async def test_long_token_masked_in_log(self, service, mock_collection, captured_log):
        mock_collection.update_one = AsyncMock()

        await service.deactivate_invalid_token(LONG_TOKEN)

        expected_mask = f"{LONG_TOKEN[:20]}...{LONG_TOKEN[-4:]}"
        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert expected_mask in logged
        assert LONG_TOKEN not in logged

    async def test_short_token_masked_in_log(self, service, mock_collection, captured_log):
        mock_collection.update_one = AsyncMock()

        assert len(SHORT_TOKEN) == 24
        await service.deactivate_invalid_token(SHORT_TOKEN)

        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert "***" in logged
        assert SHORT_TOKEN not in logged

    async def test_boundary_25_char_token_is_partially_masked(
        self, service, mock_collection, captured_log
    ):
        # 25 chars: > 24 is True, so partial mask (pins the boundary at exactly 24, not 25)
        mock_collection.update_one = AsyncMock()

        assert len(BOUNDARY_TOKEN) == 25
        await service.deactivate_invalid_token(BOUNDARY_TOKEN)

        expected_mask = f"{BOUNDARY_TOKEN[:20]}...{BOUNDARY_TOKEN[-4:]}"
        logged = " ".join(str(c.args[0]) for c in captured_log.info.call_args_list)
        assert expected_mask in logged
        assert "***" not in logged


# ---------------------------------------------------------------------------
# get_device_token_service (module-level singleton factory)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDeviceTokenServiceFactory:
    def test_builds_and_caches_singleton_on_first_call(self):
        built = MagicMock()
        with (
            patch("app.services.device_token_service.device_token_service", None),
            patch("app.db.mongodb.mongodb.init_mongodb", return_value=MagicMock()) as mock_init,
        ):
            from app.services.device_token_service import get_device_token_service

            with patch(
                "app.services.device_token_service.DeviceTokenService", return_value=built
            ) as mock_ctor:
                svc = get_device_token_service()

            assert svc is built
            mock_init.assert_called_once()
            mock_ctor.assert_called_once()

    def test_returns_cached_instance_without_reinit(self):
        cached = MagicMock()
        with (
            patch("app.services.device_token_service.device_token_service", cached),
            patch("app.db.mongodb.mongodb.init_mongodb") as mock_init,
        ):
            from app.services.device_token_service import get_device_token_service

            svc = get_device_token_service()

            assert svc is cached
            mock_init.assert_not_called()
