"""The mutation-tool factory: the envelope every state-changing tool shares.

The wrapper owns auth extraction, error formatting, analytics ordering (event
only AFTER success) and resync scheduling — each attacked here so every future
consumer inherits proven behavior instead of re-deriving it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel, Field
import pytest

from app.agents.tools.core.mutations import define_mutation_tool, user_id_from_config
from app.constants.log_tags import LogTag
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

    # Exact string: this text is the agent-facing contract for an unauthenticated
    # tool call, so a mangled variant must fail.
    assert result == "Error: user authentication required."
    apply.assert_not_awaited()


async def test_wrapper_stamps_tool_and_surface_into_the_wide_event() -> None:
    async def apply(user_id: str, *, value: int) -> str:
        return "ok"

    probe = define_mutation_tool(
        name="probe_log_set",
        area="log_area",
        description="probe",
        args_model=ProbeArgs,
        apply=apply,
    )
    with patch(f"{MODULE}.log") as log_mock:
        await probe.ainvoke({"value": 1}, config=CONFIG)

    # The wrapper's wide-event stamp is how a mutation is traced back to its
    # tool and product area — both keys must land exactly.
    log_mock.set.assert_called_once_with(
        tool={"name": "probe_log_set", "action": "mutate"},
        surface={"area": "log_area"},
    )


async def test_app_error_becomes_a_structured_error_string() -> None:
    async def apply(user_id: str, *, value: int) -> str:
        raise AppError(message="bad input", fix="be positive", status_code=400)

    result = await make_probe(apply).ainvoke({"value": -1}, config=CONFIG)

    assert result.startswith("Error: bad input")
    assert "be positive" in result


async def test_unexpected_error_is_logged_and_reported_not_raised() -> None:
    async def apply(user_id: str, *, value: int) -> str:
        raise RuntimeError("redis exploded")

    probe = define_mutation_tool(
        name="probe_fail",
        area="test_area",
        description="probe",
        args_model=ProbeArgs,
        apply=apply,
    )
    with patch(f"{MODULE}.log") as log_mock, patch(f"{MODULE}.capture_context_event"):
        result = await probe.ainvoke({"value": 1}, config=CONFIG)

    assert result == "Error: probe_fail did not complete (RuntimeError)."
    # The failure must land in the wide event's errors[] with full context:
    # which tool, what exception class, what message.
    log_mock.error.assert_called_once_with(
        f"{LogTag.TOOL} mutation failed",
        tool="probe_fail",
        error_type="RuntimeError",
        error="redis exploded",
    )


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
        assert result == "Error: user authentication required."
        apply.assert_not_awaited()


class TestUserIdFromConfig:
    def test_configurable_takes_precedence_over_metadata(self) -> None:
        config: RunnableConfig = {
            "configurable": {"user_id": "cfg-user"},
            "metadata": {"user_id": "meta-user"},
        }
        assert user_id_from_config(config) == "cfg-user"

    def test_metadata_is_the_fallback_when_configurable_has_no_user(self) -> None:
        config: RunnableConfig = {
            "configurable": {},
            "metadata": {"user_id": "meta-user"},
        }
        assert user_id_from_config(config) == "meta-user"

    def test_config_without_a_metadata_key_yields_none_not_a_crash(self) -> None:
        # The metadata lookup must default to {} — a config that carries only
        # `configurable` (the workflow/silent-run shape) must not explode.
        assert user_id_from_config({"configurable": {}}) is None

    def test_none_and_non_string_user_ids_are_rejected(self) -> None:
        assert user_id_from_config(None) is None
        assert user_id_from_config({}) is None
        assert user_id_from_config({"metadata": {"user_id": 123}}) is None
        assert user_id_from_config({"metadata": {"user_id": None}}) is None

    def test_whitespace_only_user_id_becomes_none_and_valid_ids_are_stripped(self) -> None:
        assert user_id_from_config({"metadata": {"user_id": "   "}}) is None
        assert user_id_from_config({"metadata": {"user_id": "  u-1  "}}) == "u-1"


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
