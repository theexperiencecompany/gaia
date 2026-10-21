"""Tests for the OAuth callbacks' reconnect lookup."""

from __future__ import annotations

from unittest.mock import patch

from pymongo.errors import PyMongoError
import pytest

from app.constants.log_tags import LogTag
from app.services.integrations.user_integration_status import reconnect_or_unknown

MODULE = "app.services.integrations.user_integration_status"


async def _answer(value: bool) -> bool:
    return value


async def _raise(error: Exception) -> bool:
    raise error


class TestReconnectOrUnknown:
    @pytest.mark.parametrize("connected_before", [True, False])
    async def test_an_answer_is_passed_through(self, connected_before: bool) -> None:
        assert await reconnect_or_unknown(_answer(connected_before), "gmail") is connected_before

    async def test_a_mongo_failure_is_unknown_and_names_the_integration(self) -> None:
        with patch(f"{MODULE}.log") as log:
            result = await reconnect_or_unknown(_raise(PyMongoError("down")), "gmail")

        assert result is None
        log.warning.assert_called_once()
        assert log.warning.call_args.args == (
            f"{LogTag.INTEGRATION} Could not tell whether the connect is a reconnect",
        )
        assert log.warning.call_args.kwargs == {
            "integration_id": "gmail",
            "error_type": "PyMongoError",
        }

    async def test_any_other_failure_still_raises(self) -> None:
        with pytest.raises(RuntimeError, match="bug"):
            await reconnect_or_unknown(_raise(RuntimeError("bug")), "gmail")
