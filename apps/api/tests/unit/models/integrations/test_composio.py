"""Unit tests for the Composio custom-tool auth_credentials model."""

import pytest

from app.models.integrations.composio import CustomToolAuthCredentials


class TestCustomToolAuthCredentials:
    def test_parses_user_id_and_version_and_ignores_oauth_state(self) -> None:
        creds = CustomToolAuthCredentials.parse(
            {"user_id": "user-42", "version": "2024-01-01", "status": "ACTIVE", "scope": "x"}
        )
        assert creds.user_id == "user-42"
        assert creds.version == "2024-01-01"
        assert creds.model_dump() == {"user_id": "user-42", "version": "2024-01-01"}

    def test_version_is_optional(self) -> None:
        assert CustomToolAuthCredentials.parse({"user_id": "user-42"}).version is None

    @pytest.mark.parametrize(
        "creds",
        [{}, {"user_id": ""}, {"user_id": None}, {"user_id": 123}, {"userId": "abc"}],
        ids=["missing", "blank", "none", "int", "wrong-key"],
    )
    def test_rejects_unusable_credentials(self, creds: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="^Missing user_id in auth_credentials$"):
            CustomToolAuthCredentials.parse(creds)
