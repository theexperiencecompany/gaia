"""Unit tests for app/models/composio_schemas/base.py."""

from typing import ClassVar

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.base import ComposioResponse


class TestComposioResponse:
    def test_valid_full(self):
        m = ComposioResponse(successful=True, data={"key": "value"})
        assert m.successful is True
        assert m.data == {"key": "value"}
        assert m.error is None

    def test_valid_with_error(self):
        m = ComposioResponse(successful=False, error="boom", data={})
        assert m.successful is False
        assert m.error == "boom"

    def test_valid_from_attributes(self):
        class Fake:
            successful = True
            error = None
            data: ClassVar[dict[str, int]] = {"n": 1}

        m = ComposioResponse.model_validate(Fake())
        assert m.successful is True
        assert m.data == {"n": 1}

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ComposioResponse()

    def test_missing_data(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful=True)

    def test_wrong_type_successful(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful="notabool", data={})

    def test_wrong_type_data(self):
        with pytest.raises(ValidationError):
            ComposioResponse(successful=True, data=["not", "a", "dict"])


# ---------------------------------------------------------------------------
# github trigger payloads
# ---------------------------------------------------------------------------
