"""The user-facing feature flag routes, run through the real service against an in-memory user store."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

from app.api.v1.endpoints.features import list_features, update_feature
from app.config.feature_flags import FEATURE_FLAGS, KILL_SWITCH_REASON, FeatureFlag
from app.models.user_models import UserDocument
from app.schemas.feature_flags import UpdateUserFeatureFlagRequest
from app.services.analytics_service import AnalyticsEvents

URL = "/api/v1/features"
USER_ID = FAKE_USER.user_id
SERVICE = "app.services.feature_flags"


class _UserStore:
    """Stands in for the users collection: set_feature_flag writes what get reads back."""

    def __init__(self) -> None:
        self.choices: dict[str, bool] = {}
        self.exists = True

    async def get(self, user_id: str) -> UserDocument | None:
        if not self.exists:
            return None
        return UserDocument(id=user_id, feature_flags=self.choices)

    async def set_feature_flag(self, user_id: str, flag: FeatureFlag, enabled: bool) -> bool:
        if not self.exists:
            return False
        self.choices[flag.value] = enabled
        return True


@pytest.fixture
def store() -> Iterator[_UserStore]:
    fake = _UserStore()
    with (
        patch(f"{SERVICE}.user_repository.get", side_effect=fake.get),
        patch(f"{SERVICE}.user_repository.set_feature_flag", side_effect=fake.set_feature_flag),
    ):
        yield fake


@pytest.fixture
def posthog() -> Iterator[MagicMock]:
    """One PostHog client behind both flag evaluation and event capture; flag_values holds what it serves."""
    client = MagicMock()
    client.flag_values = {}
    client.get_feature_flag.side_effect = lambda key, _user_id: client.flag_values.get(key)
    with (
        patch(f"{SERVICE}._get_posthog_client", return_value=client),
        patch("app.services.analytics_service._get_posthog_client", return_value=client),
    ):
        yield client


def _toggled_captures(client: MagicMock) -> list[dict[str, object]]:
    return [
        call.kwargs
        for call in client.capture.call_args_list
        if call.kwargs["event"] == AnalyticsEvents.FEATURE_TOGGLED
    ]


@pytest.mark.unit
class TestListFeatures:
    async def test_lists_only_user_facing_flags(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        resp = await client.get(URL)

        assert resp.status_code == 200
        assert resp.json() == {
            "features": [
                {
                    "key": "BROWSER_OBSCURA",
                    "label": "Obscura browser engine",
                    "description": FEATURE_FLAGS[
                        FeatureFlag.BROWSER_OBSCURA
                    ].user_toggle.description,
                    "stage": "experimental",
                    "enabled": False,
                    "available": True,
                    "unavailable_reason": None,
                }
            ]
        }

    async def test_shows_the_rollout_value_before_the_user_chooses(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        posthog.flag_values["BROWSER_OBSCURA"] = True

        resp = await client.get(URL)

        assert resp.json()["features"][0]["enabled"] is True

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(URL)
        assert resp.status_code == 401

    async def test_a_killed_flag_is_listed_locked_and_off_over_the_users_choice(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        store.choices["BROWSER_OBSCURA"] = True
        posthog.flag_values["BROWSER_OBSCURA_KILL"] = True

        [feature] = (await client.get(URL)).json()["features"]

        assert (feature["enabled"], feature["available"]) == (False, False)
        assert feature["unavailable_reason"] == KILL_SWITCH_REASON


@pytest.mark.unit
class TestUpdateFeature:
    async def test_round_trip_stores_the_choice_and_lists_it(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        resp = await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})

        assert resp.status_code == 200
        assert resp.json()["key"] == "BROWSER_OBSCURA"
        assert resp.json()["enabled"] is True
        assert store.choices == {"BROWSER_OBSCURA": True}
        listed = (await client.get(URL)).json()["features"]
        assert [(f["key"], f["enabled"]) for f in listed] == [("BROWSER_OBSCURA", True)]

    async def test_the_choice_beats_a_rollout_that_says_otherwise(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        posthog.flag_values["BROWSER_OBSCURA"] = True

        await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": False})

        assert (await client.get(URL)).json()["features"][0]["enabled"] is False

    async def test_toggle_is_captured_for_the_user_with_a_person_property(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})

        [captured] = _toggled_captures(posthog)
        assert captured["distinct_id"] == USER_ID
        assert captured["properties"]["flag"] == "BROWSER_OBSCURA"
        assert captured["properties"]["enabled"] is True
        posthog.set.assert_called_once_with(
            distinct_id=USER_ID, properties={"feature_browser_obscura": True}
        )

    @pytest.mark.parametrize("flag", ["COMMS_OPENUI", "CODE_MODE", "NOT_A_FLAG"])
    async def test_internal_and_unknown_flags_are_404(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock, flag: str
    ) -> None:
        resp = await client.patch(f"{URL}/{flag}", json={"enabled": True})

        assert resp.status_code == 404
        assert resp.json()["message"] == "Feature not found"
        assert store.choices == {}
        assert _toggled_captures(posthog) == []

    async def test_a_missing_user_is_404_and_captures_nothing(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        store.exists = False

        resp = await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})

        assert resp.status_code == 404
        assert _toggled_captures(posthog) == []

    async def test_patch_while_killed_is_a_409_and_stores_nothing(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        store.choices["BROWSER_OBSCURA"] = False
        posthog.flag_values["BROWSER_OBSCURA_KILL"] = True

        resp = await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})

        assert resp.status_code == 409
        assert resp.json()["code"] == "FEATURE_KILLED"
        assert store.choices == {"BROWSER_OBSCURA": False}
        assert _toggled_captures(posthog) == []
        posthog.set.assert_not_called()

    async def test_patch_with_posthog_down_is_not_blocked(
        self, client: AsyncClient, store: _UserStore, posthog: MagicMock
    ) -> None:
        posthog.get_feature_flag.side_effect = TimeoutError("posthog down")

        resp = await client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})

        assert resp.status_code == 200
        assert resp.json()["available"] is True
        assert store.choices == {"BROWSER_OBSCURA": True}

    async def test_a_missing_body_is_a_422(self, client: AsyncClient) -> None:
        resp = await client.patch(f"{URL}/BROWSER_OBSCURA")
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.patch(f"{URL}/BROWSER_OBSCURA", json={"enabled": True})
        assert resp.status_code == 401


@pytest.mark.unit
@pytest.mark.usefixtures("store", "posthog")
class TestWideEvent:
    async def test_a_listing_records_who_asked_and_how_many_flags_they_saw(self) -> None:
        async with captured_wide_event() as event:
            await list_features(user=FAKE_USER)

        assert event["user"] == {"id": USER_ID}
        assert event["feature"] == {"operation": "list", "count": 1}

    async def test_a_toggle_records_the_flag_the_choice_and_what_was_stored(self) -> None:
        async with captured_wide_event() as event:
            await update_feature(
                "BROWSER_OBSCURA", UpdateUserFeatureFlagRequest(enabled=True), user=FAKE_USER
            )

        assert event["user"] == {"id": USER_ID}
        assert event["feature"] == {
            "operation": "toggle",
            "flag": "BROWSER_OBSCURA",
            "enabled": True,
            "stored": True,
        }
