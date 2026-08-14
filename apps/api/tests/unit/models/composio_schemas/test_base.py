"""Unit tests for ``app.models.composio_schemas.base`` — the shared Composio response shell."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.base import ComposioResponse


def test_successful_response_parses_with_nested_data() -> None:
    response = ComposioResponse.model_validate(
        {"successful": True, "data": {"items": [{"id": 1}], "count": 2}}
    )
    assert response.successful is True
    assert response.error is None
    assert response.data == {"items": [{"id": 1}], "count": 2}


def test_error_response_carries_error_and_empty_data() -> None:
    response = ComposioResponse.model_validate(
        {"successful": False, "error": "tool not found", "data": {}}
    )
    assert response.successful is False
    assert response.error == "tool not found"
    assert response.data == {}


def test_data_field_is_required() -> None:
    """``data`` is mandatory on every Composio tool response."""
    with pytest.raises(ValidationError):
        ComposioResponse.model_validate({"successful": True})


def test_data_accepts_non_string_values() -> None:
    """``data: dict[str, object]`` must accept ints/lists/bools as values —
    a str-typed value dict would reject real Composio payloads."""
    response = ComposioResponse.model_validate(
        {"successful": True, "data": {"n": 5, "flag": True, "tags": ["a", "b"]}}
    )
    assert response.data["n"] == 5
    assert response.data["flag"] is True
    assert response.data["tags"] == ["a", "b"]
