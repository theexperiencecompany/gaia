"""The mutation-tool factory: the envelope every state-changing tool shares.

The wrapper owns auth extraction, error formatting, analytics ordering (event
only AFTER success) and resync scheduling — each attacked here so every future
consumer inherits proven behavior instead of re-deriving it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, Field
import pytest

from app.agents.tools.core.mutations import define_mutation_tool
from app.utils.errors import AppError

MODULE = "app.agents.tools.core.mutations"
CONFIG = {"metadata": {"user_id": "user-1"}}


class ProbeArgs(BaseModel):
    value: int = Field(description="probe value")


def make_probe(
    apply,
    **kwargs,
):
    return define_mutation_tool(
        name=f"probe_{id(apply)}",
        area="test_area",
        description="probe",
        args_model=ProbeArgs,
        apply=apply,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _quiet():
    with (
        patch(f"{MODULE}.log"),
        patch(f"{MODULE}.capture_context_event") as capture,
    ):
        yield capture


async def test_apply_receives_config_user_id_and_schema_kwargs() -> None:
    seen = {}

    async def apply(user_id: str, *, value: int) -> str:
        seen["user_id"] = user_id
        seen["value"] = value
        # A distinctive sentinel: a wrapper that returns any constant instead of
        # the applier's own confirmation must fail this assertion.
        return f"applied:{value}:{user_id}"

    result = await make_probe(apply).ainvoke({"value": 3}, config=CONFIG)

    assert result == "applied:3:user-1"
    assert seen == {"user_id": "user-1", "value": 3}


async def test_missing_user_fails_without_calling_apply() -> None:
    apply = AsyncMock(return_value="done")
    result = await make_probe(apply).ainvoke({"value": 1}, config={})

    assert "authentication required" in result
    apply.assert_not_awaited()


async def test_app_error_becomes_a_structured_error_string() -> None:
    async def apply(user_id: str, *, value: int) -> str:
        raise AppError(message="bad input", fix="be positive", status_code=400)

    result = await make_probe(apply).ainvoke({"value": -1}, config=CONFIG)

    assert result.startswith("Error: bad input")
    assert "be positive" in result


async def test_unexpected_error_is_logged_and_reported_not_raised() -> None:
    async def apply(user_id: str, *, value: int) -> str:
        raise RuntimeError("redis exploded")

    result = await make_probe(apply).ainvoke({"value": 1}, config=CONFIG)

    assert result.startswith("Error:")
    assert "did not complete" in result


async def test_event_captures_only_after_success(_quiet) -> None:
    async def failing(user_id: str, *, value: int) -> str:
        raise RuntimeError("no")

    await make_probe(failing).ainvoke({"value": 1}, config=CONFIG)
    _quiet.assert_not_called()

    async def succeeding(user_id: str, *, value: int) -> str:
        return "ok"

    probe = define_mutation_tool(
        name="probe_event",
        area="test_area",
        description="probe",
        args_model=ProbeArgs,
        apply=succeeding,
        event="account:test_event",
    )
    with patch(f"{MODULE}.capture_context_event") as capture:
        await probe.ainvoke({"value": 1}, config=CONFIG)
    capture.assert_called_once_with("account:test_event", {"area": "test_area"})


async def test_resync_schedules_after_success_only() -> None:
    resync = SimpleNamespace(calls=[])

    def track(user_id: str) -> None:
        resync.calls.append(user_id)

    async def failing(user_id: str, *, value: int) -> str:
        raise RuntimeError("no")

    probe = define_mutation_tool(
        name="probe_resync_fail",
        area="a",
        description="p",
        args_model=ProbeArgs,
        apply=failing,
        resync=track,
    )
    await probe.ainvoke({"value": 1}, config=CONFIG)
    assert resync.calls == []

    async def succeeding(user_id: str, *, value: int) -> str:
        return "ok"

    probe = define_mutation_tool(
        name="probe_resync_ok",
        area="a",
        description="p",
        args_model=ProbeArgs,
        apply=succeeding,
        resync=track,
    )
    await probe.ainvoke({"value": 1}, config=CONFIG)
    assert resync.calls == ["user-1"]


class TestUserIdExtraction:
    async def test_configurable_user_id_is_used_without_metadata(self) -> None:
        seen = {}

        async def apply(user_id: str, *, value: int) -> str:
            seen["user_id"] = user_id
            return "ok"

        await make_probe(apply).ainvoke(
            {"value": 1}, config={"configurable": {"user_id": "cfg-user"}}
        )
        assert seen["user_id"] == "cfg-user"

    async def test_blank_string_user_ids_are_rejected_not_trusted(self) -> None:
        apply = AsyncMock(return_value="done")
        result = await make_probe(apply).ainvoke(
            {"value": 1}, config={"metadata": {"user_id": "   "}}
        )
        assert "authentication required" in result
        apply.assert_not_awaited()


async def test_unknown_schema_keys_are_dropped_before_apply_sees_them() -> None:
    seen = {}

    async def apply(user_id: str, *, value: int) -> str:
        seen.update(value=value)
        return "ok"

    # An LLM hallucinating an extra arg must not reach apply as garbage.
    await make_probe(apply).ainvoke({"value": 7, "evil_key": "<script>"}, config=CONFIG)
    assert seen == {"value": 7}


async def test_event_and_resync_fire_together_exactly_once_on_success() -> None:
    with patch(f"{MODULE}.capture_context_event") as capture:
        resync_calls: list[str] = []

        async def apply(user_id: str, *, value: int) -> str:
            return "ok"

        probe = define_mutation_tool(
            name="probe_combo",
            area="combo_area",
            description="p",
            args_model=ProbeArgs,
            apply=apply,
            event="test:event",
            resync=resync_calls.append,
        )
        await probe.ainvoke({"value": 1}, config=CONFIG)

    capture.assert_called_once_with("test:event", {"area": "combo_area"})
    assert resync_calls == ["user-1"]
