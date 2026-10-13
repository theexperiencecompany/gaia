"""CustomTool input coercion: LangChain-side lookalike instances must validate.

Composio builds the LangChain tool's args_schema by regenerating Pydantic
models from JSON schema (json_schema_to_pydantic), so the instances
LangChain hands to invoke_trusted are NOT instances of our real input
models. The real model's isinstance check then rejects them with a
model_type error that shows a perfectly good instance being refused.
Coercing to plain data before the real validation fixes every nested-model
custom tool at the one boundary where the identities collide.
"""

from collections.abc import Callable
from datetime import UTC, datetime
import inspect
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from composio.core.models.custom_tools import CustomTool
from composio.utils import shared
from pydantic import BaseModel, ValidationError
import pytest

from app.constants.log_tags import LogTag
from app.models.calendar_models import CreateEventInput, SingleEventInput
from app.patches import composio_custom_tool_input_patch as patch_mod
from app.patches.composio_custom_tool_input_patch import to_plain_data
from tests.helpers import captured_wide_event


def _lookalike_of(model: type) -> type:
    """Build a same-shaped model the way Composio rebuilds ours from schema."""
    rebuilt = shared.json_schema_to_pydantic_type(model.model_json_schema())
    assert isinstance(rebuilt, type), "expected a rebuilt model class"
    return rebuilt


def _event_dict() -> dict[str, Any]:
    return {
        "events": [{"summary": "s", "start_datetime": "2026-09-26T11:00:00"}],
    }


def _lookalike_event_kwargs() -> dict[str, Any]:
    """Request kwargs carrying a rebuilt SingleEventInput, as LangChain hands them down."""
    lookalike_item = _lookalike_of(SingleEventInput)
    assert lookalike_item is not SingleEventInput
    nested = lookalike_item.model_validate(
        {"summary": "s", "start_datetime": "2026-09-26T11:00:00"}
    )
    return {"events": [nested]}


class _StampedRecord(BaseModel):
    at: datetime
    ref: UUID


@pytest.mark.unit
class TestLookalikeCollision:
    def test_rebuilt_instance_fails_real_validation_without_coercion(self) -> None:
        """Pins the production failure: same shape, different class identity."""
        lookalike = _lookalike_of(CreateEventInput)
        assert lookalike is not CreateEventInput
        instance = lookalike.model_validate(_event_dict())
        with pytest.raises(ValidationError, match="model_type"):
            CreateEventInput.model_validate(instance)

    def test_coerced_plain_data_passes_real_validation(self) -> None:
        lookalike = _lookalike_of(CreateEventInput)
        instance = lookalike.model_validate(_event_dict())
        coerced = to_plain_data({"request": instance, "flag": True})
        assert coerced == {
            "request": {
                "events": [
                    {
                        "summary": "s",
                        "start_datetime": "2026-09-26T11:00:00",
                        "end_datetime": None,
                        "calendar_id": "primary",
                        "description": None,
                        "location": None,
                        "attendees": None,
                        "is_all_day": False,
                        "create_meeting_room": False,
                    }
                ],
            },
            "flag": True,
        }
        validated = CreateEventInput.model_validate(coerced["request"])
        assert validated.events[0].summary == "s"

    def test_plain_data_passes_through_untouched(self) -> None:
        plain = {"a": [1, {"b": None}], "c": "x"}
        assert to_plain_data(plain) == plain

    def test_non_json_native_fields_dump_to_their_json_form(self) -> None:
        record = _StampedRecord(
            at=datetime(2026, 9, 26, 11, 0, tzinfo=UTC),
            ref=UUID("12345678-1234-5678-1234-567812345678"),
        )
        assert to_plain_data([record]) == [
            {"at": "2026-09-26T11:00:00Z", "ref": "12345678-1234-5678-1234-567812345678"}
        ]


@pytest.mark.unit
class TestInvokeTrustedWrapper:
    def _stub_tool(self) -> Any:
        return SimpleNamespace(
            request_model=CreateEventInput,
            toolkit=None,
            f=lambda request: {"summary": request.events[0].summary},
        )

    def test_lookalike_kwargs_execute_end_to_end(self) -> None:
        """The wrapper coerces before the real validation: a rebuilt instance nested in kwargs runs the function instead of raising model_type."""
        kwargs = _lookalike_event_kwargs()
        seen_user_ids: list[str] = []

        def fake_original(self: Any, user_id: str, request_kwargs: Any) -> Any:
            seen_user_ids.append(user_id)
            validated = CreateEventInput.model_validate(request_kwargs)
            return self.f(request=validated)

        # Without coercion this is the production failure, verbatim.
        with pytest.raises(ValidationError, match="model_type"):
            fake_original(self._stub_tool(), "u1", kwargs)

        previous, patch_mod._original_invoke_trusted = (
            patch_mod._original_invoke_trusted,
            fake_original,
        )
        try:
            bound = patch_mod._coercing_invoke_trusted.__get__(self._stub_tool(), object)
            result = bound("u1", kwargs)
        finally:
            patch_mod._original_invoke_trusted = previous
        assert result == {"summary": "s"}
        assert seen_user_ids == ["u1", "u1"]

    def test_apply_wraps_once_and_marks(self) -> None:
        patch_mod.apply()
        first = CustomTool.invoke_trusted
        assert getattr(first, "__gaia_coercing__", False) is True
        patch_mod.apply()
        assert CustomTool.invoke_trusted is first


def _create_events(request: CreateEventInput) -> dict[str, str]:
    """Create calendar events."""
    return {"summary": request.events[0].summary}


@pytest.mark.unit
class TestApply:
    """Re-run apply() against the library's own invoke_trusted, not the state import left behind."""

    @pytest.fixture
    def library_invoke_trusted(self, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
        library_original = patch_mod._original_invoke_trusted
        monkeypatch.setattr(CustomTool, "invoke_trusted", library_original)
        monkeypatch.setattr(patch_mod, "_applied", False)
        monkeypatch.setattr(patch_mod, "_original_invoke_trusted", None)
        monkeypatch.delattr(patch_mod._coercing_invoke_trusted, "__wrapped__", raising=False)
        return library_original

    def test_applied_twice_a_real_tool_runs_lookalike_input_through_the_library_dispatch(
        self, library_invoke_trusted: Callable[..., Any]
    ) -> None:
        patch_mod.apply()
        patch_mod.apply()
        tool = CustomTool(f=_create_events, client=MagicMock())

        result = tool.invoke_trusted("u1", _lookalike_event_kwargs())

        assert result == {"summary": "s"}

    def test_unwrap_reaches_the_library_dispatch(
        self, library_invoke_trusted: Callable[..., Any]
    ) -> None:
        patch_mod.apply()

        assert inspect.unwrap(CustomTool.invoke_trusted) is library_invoke_trusted

    async def test_a_failed_apply_is_reported_and_leaves_the_library_untouched(
        self, library_invoke_trusted: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module_name = "composio.core.models.custom_tools"
        monkeypatch.setitem(sys.modules, module_name, None)

        async with captured_wide_event() as event:
            patch_mod.apply()

        assert CustomTool.invoke_trusted is library_invoke_trusted
        assert patch_mod._applied is False
        assert event["errors"] == [
            {
                "msg": f"{LogTag.PATCH} Failed to apply custom_tool input patch",
                "patch": "composio_custom_tool_input",
                "error": f"import of {module_name} halted; None in sys.modules",
                "error_type": "ModuleNotFoundError",
            }
        ]
