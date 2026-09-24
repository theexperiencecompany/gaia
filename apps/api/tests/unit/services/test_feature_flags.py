"""Unit tests for app/services/feature_flags.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.feature_flags import FEATURE_FLAGS, FeatureFlag, FeatureStage, kill_switch_key
from app.config.settings import settings as app_settings
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.feature_flags import (
    _coerce_result,
    _get_posthog_client,
    is_code_mode_enabled,
    is_enabled,
    is_hil_ledger_enabled,
)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    with patch("app.services.feature_flags._get_posthog_client", return_value=client):
        yield client


@pytest.fixture
def no_client() -> None:
    with patch("app.services.feature_flags._get_posthog_client", return_value=None):
        yield


@pytest.fixture
def evaluated() -> MagicMock:
    with patch("app.services.feature_flags.capture_event") as mocked:
        yield mocked


class TestNoUserId:
    async def test_no_user_returns_default_without_io(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, None) is True
        mock_client.get_feature_flag.assert_not_called()
        evaluated.assert_not_called()

    async def test_explicit_default_wins_without_user(self) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, None, default=False) is False


class TestLiveEvaluation:
    async def test_true_evaluates_every_call(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        """No cache: consecutive evaluations each hit PostHog so a dashboard flip applies on the very next turn."""
        mock_client.get_feature_flag.return_value = True
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert mock_client.get_feature_flag.call_count == 2
        mock_client.get_feature_flag.assert_called_with("COMMS_OPENUI", "u1")

    async def test_false_disables(self, mock_client: MagicMock, evaluated: MagicMock) -> None:
        mock_client.get_feature_flag.return_value = False
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is False

    async def test_none_falls_back_to_default(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = None
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1", default=False) is False

    async def test_exception_fails_open(self, mock_client: MagicMock, evaluated: MagicMock) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True

    async def test_no_client_falls_back(self, no_client: None) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True


class TestEvaluationEvent:
    async def test_successful_evaluation_emits_nothing(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        """The SDK auto-emits $feature_flag_called on success; our event covers only the paths it cannot see, so this must stay silent."""
        mock_client.get_feature_flag.return_value = True
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        evaluated.assert_not_called()

    async def test_disabled_value_emits_nothing(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = False
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is False
        evaluated.assert_not_called()

    async def test_unevaluated_flag_names_the_reason(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = None
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        call = evaluated.call_args
        assert call.args[0] == "u1"
        assert call.args[1] == AnalyticsEvents.FEATURE_FLAG_EVALUATED
        assert call.args[2]["flag"] == "COMMS_OPENUI"
        assert call.args[2]["enabled"] is True
        assert call.args[2]["fallback_reason"] == "flag_unevaluated"
        assert call.kwargs["dedupe_key"].startswith("feature-flag-evaluated:COMMS_OPENUI:u1:")

    async def test_fail_open_names_the_reason(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert evaluated.call_args.args[2]["fallback_reason"] == "evaluation_error"

    async def test_unconfigured_posthog_still_counts_fallback(
        self, no_client: None, evaluated: MagicMock
    ) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert evaluated.call_args.args[2]["fallback_reason"] == "posthog_unconfigured"


class TestCoerce:
    def test_none_is_default(self) -> None:
        assert _coerce_result(None, True) is True
        assert _coerce_result(None, False) is False

    def test_control_strings_disable(self) -> None:
        for variant in ("false", "control", "disabled", "off"):
            assert _coerce_result(variant, True) is False

    def test_variant_string_enables(self) -> None:
        assert _coerce_result("test-variant", False) is True


class TestFlags:
    async def test_is_code_mode_enabled_defaults_off(self, no_client: None) -> None:
        assert await is_code_mode_enabled("u1") is False

    async def test_is_code_mode_enabled_live(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        assert await is_code_mode_enabled("u1") is True
        mock_client.get_feature_flag.assert_called_once_with("CODE_MODE", "u1")

    async def test_is_hil_ledger_enabled_defaults_off(self, no_client: None) -> None:
        assert await is_hil_ledger_enabled("u1") is False

    async def test_is_hil_ledger_enabled_live(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        assert await is_hil_ledger_enabled("u1") is True
        mock_client.get_feature_flag.assert_called_once_with("HIL_LEDGER", "u1")

    def test_feature_flag_evaluated_event_name(self) -> None:
        assert AnalyticsEvents.FEATURE_FLAG_EVALUATED == "feature_flag:evaluated"

    def test_flag_keys_match_dashboard(self) -> None:
        assert FeatureFlag.COMMS_OPENUI == "COMMS_OPENUI"
        assert FeatureFlag.CODE_MODE == "CODE_MODE"


class TestExplicitDefaultIsFallbackOnly:
    """default= applies when PostHog cannot decide — it never overrides a live evaluation."""

    async def test_live_true_beats_explicit_false(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1", default=False) is True

    async def test_live_false_beats_explicit_true(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = False
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1", default=True) is False

    async def test_exception_uses_explicit_default(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1", default=False) is False
        assert evaluated.call_args.args[2]["enabled"] is False
        assert evaluated.call_args.args[2]["fallback_reason"] == "evaluation_error"


class TestFalsyUserId:
    async def test_empty_user_id_means_no_evaluation(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "") is True
        mock_client.get_feature_flag.assert_not_called()
        evaluated.assert_not_called()


class TestClientLookup:
    def test_unavailable_provider_yields_none(self) -> None:
        with patch(
            "app.services.feature_flags.providers.is_available", return_value=False
        ) as available:
            assert _get_posthog_client() is None
            available.assert_called_once_with("posthog")

    def test_registry_key_error_yields_none(self) -> None:
        with (
            patch("app.services.feature_flags.providers.is_available", return_value=True),
            patch(
                "app.services.feature_flags.providers.get",
                side_effect=KeyError("posthog"),
            ),
        ):
            assert _get_posthog_client() is None


class TestTrackingNeverBreaksEvaluation:
    async def test_capture_failure_still_returns_live_value(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        evaluated.side_effect = RuntimeError("telemetry down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True

    async def test_capture_failure_still_returns_fallback(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        evaluated.side_effect = RuntimeError("telemetry down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True


class TestCoerceExtended:
    def test_whitespace_and_case_insensitive(self) -> None:
        assert _coerce_result(" False ", True) is False
        assert _coerce_result("CONTROL", True) is False
        assert _coerce_result("True", False) is True

    def test_non_string_truthiness(self) -> None:
        assert _coerce_result(1, False) is True
        assert _coerce_result(0, True) is False


class TestHelpersWithoutUser:
    async def test_code_mode_none_user_is_default(self, evaluated: MagicMock) -> None:
        assert await is_code_mode_enabled(None) is False
        evaluated.assert_not_called()


class TestRegistry:
    def test_every_flag_is_declared_with_a_description(self) -> None:
        assert set(FEATURE_FLAGS) == set(FeatureFlag)
        assert all(spec.description for spec in FEATURE_FLAGS.values())

    def test_flag_keys_unique(self) -> None:
        assert len({f.value for f in FeatureFlag}) == len(list(FeatureFlag))

    async def test_dedupe_key_carries_today(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        from datetime import UTC, datetime

        mock_client.get_feature_flag.return_value = None
        await is_enabled(FeatureFlag.COMMS_OPENUI, "u9")
        key = evaluated.call_args.kwargs["dedupe_key"]
        assert key.endswith(datetime.now(UTC).date().isoformat())


class TestClientPassthrough:
    def test_available_provider_returns_its_client(self) -> None:
        sentinel = object()
        with (
            patch("app.services.feature_flags.providers.is_available", return_value=True),
            patch("app.services.feature_flags.providers.get", return_value=sentinel) as get,
        ):
            assert _get_posthog_client() is sentinel
            get.assert_called_once_with("posthog")


class TestHelperDelegation:
    async def test_code_mode_helper_forwards_flag_and_user(self, evaluated: MagicMock) -> None:
        with patch(
            "app.services.feature_flags.is_enabled",
            return_value=True,
        ) as enabled:
            assert await is_code_mode_enabled("u3") is True
            enabled.assert_called_once_with(FeatureFlag.CODE_MODE, "u3")


class TestCodeModeDefaultFollowsSettings:
    async def test_code_mode_default_true_when_env_enables(
        self, monkeypatch: pytest.MonkeyPatch, no_client: None, evaluated: MagicMock
    ) -> None:
        from app.config.settings import settings

        monkeypatch.setattr(settings, "ENABLE_CODE_MODE", True)
        assert await is_code_mode_enabled("u1") is True


FLAG_KILL_SWITCHES = {
    FeatureFlag.COMMS_OPENUI: "ENABLE_COMMS_OPENUI",
    FeatureFlag.CODE_MODE: "ENABLE_CODE_MODE",
    FeatureFlag.HIL_LEDGER: "ENABLE_HIL_LEDGER",
    FeatureFlag.HIL_JEV_JUDGE: "ENABLE_HIL_JEV_JUDGE",
    FeatureFlag.HIL_JEV_REPLY: "ENABLE_HIL_JEV_REPLY",
}


class TestEveryFlagFailsOpenToItsOwnSetting:
    def test_every_internal_flag_has_a_kill_switch(self) -> None:
        internal = {flag for flag, spec in FEATURE_FLAGS.items() if spec.user_toggle is None}
        assert set(FLAG_KILL_SWITCHES) == internal

    @pytest.mark.parametrize("flag", list(FLAG_KILL_SWITCHES), ids=lambda flag: flag.value)
    @pytest.mark.parametrize("env_value", [True, False])
    async def test_an_unevaluated_flag_serves_its_env_default(
        self,
        flag: FeatureFlag,
        env_value: bool,
        monkeypatch: pytest.MonkeyPatch,
        no_client: None,
        evaluated: MagicMock,
    ) -> None:
        for other in FLAG_KILL_SWITCHES.values():
            monkeypatch.setattr(app_settings, other, not env_value)
        monkeypatch.setattr(app_settings, FLAG_KILL_SWITCHES[flag], env_value)

        assert await is_enabled(flag, "u1") is env_value


class TestCoerceEmptyString:
    def test_empty_string_disables(self) -> None:
        assert _coerce_result("", True) is False


class TestTrackingIdentity:
    async def test_unconfigured_tracks_user_and_enabled(
        self, no_client: None, evaluated: MagicMock
    ) -> None:
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        call = evaluated.call_args
        assert call.args[0] == "u1"
        assert call.args[2]["enabled"] is True

    async def test_error_path_tracks_user(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
        assert evaluated.call_args.args[0] == "u1"


class TestLogContract:
    """Log lines are the wide event's diagnostics: pin the exact call so a dropped context field fails loudly instead of silently degrading the telemetry the on-call reads."""

    def test_unavailable_client_logs_debug(self) -> None:
        with (
            patch("app.services.feature_flags.providers.is_available", return_value=False),
            patch("app.services.feature_flags.log") as mock_log,
        ):
            assert _get_posthog_client() is None
            mock_log.debug.assert_called_once_with(
                "PostHog client not available, flag falls back to default"
            )

    def test_lookup_failure_logs_debug_with_cause(self) -> None:
        with (
            patch("app.services.feature_flags.providers.is_available", return_value=True),
            patch(
                "app.services.feature_flags.providers.get",
                side_effect=KeyError("posthog"),
            ),
            patch("app.services.feature_flags.log") as mock_log,
        ):
            assert _get_posthog_client() is None
            mock_log.debug.assert_called_once_with(
                "PostHog provider lookup failed, flag falls back to default",
                error="'posthog'",
                error_type="KeyError",
            )

    async def test_evaluation_error_logs_warning_with_cause(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")
        with patch("app.services.feature_flags.log") as mock_log:
            assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
            mock_log.warning.assert_called_once_with(
                "Feature flag evaluation failed, falling back to default",
                flag="COMMS_OPENUI",
                error="posthog down",
                error_type="TimeoutError",
            )

    async def test_live_evaluation_stamps_wide_event(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        with patch("app.services.feature_flags.log") as mock_log:
            assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
            mock_log.set.assert_called_once_with(flags={"COMMS_OPENUI": True})

    async def test_tracking_failure_logs_debug_with_cause(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = None
        evaluated.side_effect = RuntimeError("telemetry down")
        with patch("app.services.feature_flags.log") as mock_log:
            assert await is_enabled(FeatureFlag.COMMS_OPENUI, "u1") is True
            mock_log.debug.assert_called_once_with(
                "Feature flag evaluation event skipped",
                flag="COMMS_OPENUI",
                error="telemetry down",
                error_type="RuntimeError",
            )

    async def test_dedupe_clock_is_utc(self, mock_client: MagicMock, evaluated: MagicMock) -> None:
        from datetime import UTC, datetime as real_datetime

        mock_client.get_feature_flag.return_value = None
        with patch("app.services.feature_flags.datetime") as mock_dt:
            mock_dt.now.return_value = real_datetime.now(UTC)
            await is_enabled(FeatureFlag.COMMS_OPENUI, "u1")
            mock_dt.now.assert_called_once_with(UTC)


USER_ID = "64abc123def4567890abcdef"


def _user_with_choices(choices: dict[str, bool] | None) -> UserDocument:
    return UserDocument(id=USER_ID, feature_flags=choices)


def _posthog_serves(client: MagicMock, values: dict[str, object]) -> None:
    """Answer each PostHog flag key from values; a key it lacks is unevaluated (None)."""
    client.get_feature_flag.side_effect = lambda key, _user_id: values.get(key)


def _queried_keys(client: MagicMock) -> list[str]:
    return [call.args[0] for call in client.get_feature_flag.call_args_list]


@pytest.fixture
def stored_user() -> AsyncMock:
    with patch("app.services.feature_flags.user_repository.get", new_callable=AsyncMock) as get:
        yield get


class TestUserFlagRegistry:
    def test_obscura_is_the_one_user_facing_flag_and_off_by_default(self) -> None:
        user_facing = [flag for flag, spec in FEATURE_FLAGS.items() if spec.user_toggle]
        assert user_facing == [FeatureFlag.BROWSER_OBSCURA]
        spec = FEATURE_FLAGS[FeatureFlag.BROWSER_OBSCURA]
        assert spec.default() is False
        assert spec.user_toggle is not None
        assert spec.user_toggle.label == "Obscura browser engine"
        assert spec.user_toggle.stage is FeatureStage.EXPERIMENTAL

    def test_every_user_facing_flag_carries_settings_copy(self) -> None:
        for spec in FEATURE_FLAGS.values():
            if spec.user_toggle is not None:
                assert spec.user_toggle.label
                assert spec.user_toggle.description


class TestEvaluationOrder:
    """Stored choice beats PostHog beats the default, and only for user-facing flags."""

    @pytest.mark.parametrize("choice", [True, False])
    async def test_stored_choice_beats_posthog(
        self,
        choice: bool,
        stored_user: AsyncMock,
        mock_client: MagicMock,
        evaluated: MagicMock,
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": choice})
        _posthog_serves(mock_client, {"BROWSER_OBSCURA": not choice})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is choice
        assert "BROWSER_OBSCURA" not in _queried_keys(mock_client)
        stored_user.assert_awaited_once_with(USER_ID)

    async def test_the_choice_counts_in_the_exposure_denominator(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        _posthog_serves(mock_client, {})

        await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID)

        assert evaluated.call_args.args[0] == USER_ID
        assert evaluated.call_args.args[2] == {
            "flag": "BROWSER_OBSCURA",
            "enabled": True,
            "fallback_reason": "user_choice",
        }

    @pytest.mark.parametrize("choices", [None, {}], ids=["never_chose", "chose_other_flags"])
    async def test_without_a_choice_posthog_decides(
        self,
        choices: dict[str, bool] | None,
        stored_user: AsyncMock,
        mock_client: MagicMock,
        evaluated: MagicMock,
    ) -> None:
        stored_user.return_value = _user_with_choices(choices)
        _posthog_serves(mock_client, {"BROWSER_OBSCURA": True})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True
        mock_client.get_feature_flag.assert_any_call("BROWSER_OBSCURA", USER_ID)

    async def test_without_a_choice_or_rollout_the_default_is_off(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices(None)
        mock_client.get_feature_flag.return_value = None

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is False

    async def test_a_missing_user_falls_through_to_posthog(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = None
        _posthog_serves(mock_client, {"BROWSER_OBSCURA": True})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True

    async def test_an_internal_flag_ignores_a_stored_choice(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"CODE_MODE": True})
        mock_client.get_feature_flag.return_value = False

        assert await is_enabled(FeatureFlag.CODE_MODE, USER_ID) is False
        stored_user.assert_not_awaited()

    async def test_no_user_reads_no_choice(
        self, stored_user: AsyncMock, mock_client: MagicMock
    ) -> None:
        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, None) is False
        stored_user.assert_not_awaited()


class TestKillSwitch:
    """The dashboard's <FLAG>_KILL forces a user-facing flag off for everyone, over every choice."""

    async def test_kill_switch_beats_a_stored_choice(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        _posthog_serves(mock_client, {"BROWSER_OBSCURA_KILL": True, "BROWSER_OBSCURA": True})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is False
        assert evaluated.call_args.args[2] == {
            "flag": "BROWSER_OBSCURA",
            "enabled": False,
            "fallback_reason": "killed",
        }

    async def test_kill_switch_beats_a_rollout(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices(None)
        _posthog_serves(mock_client, {"BROWSER_OBSCURA_KILL": True, "BROWSER_OBSCURA": True})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is False
        assert "BROWSER_OBSCURA" not in _queried_keys(mock_client)

    async def test_posthog_down_leaves_the_kill_switch_off_and_the_choice_stands(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        mock_client.get_feature_flag.side_effect = TimeoutError("posthog down")

        with patch("app.services.feature_flags.log") as mock_log:
            assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True
        mock_log.warning.assert_called_once_with(
            "Feature flag kill switch check failed, leaving it disengaged",
            flag="BROWSER_OBSCURA",
            kill_switch="BROWSER_OBSCURA_KILL",
            error="posthog down",
            error_type="TimeoutError",
        )
        assert evaluated.call_args.args[2]["fallback_reason"] == "user_choice"

    async def test_an_unanswered_kill_switch_is_logged_and_off(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        """The SDK turns a connection error into None, so None must be as visible as a raise."""
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        _posthog_serves(mock_client, {})

        with patch("app.services.feature_flags.log") as mock_log:
            assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True
        mock_log.warning.assert_called_once_with(
            "Feature flag kill switch unevaluated, leaving it disengaged",
            flag="BROWSER_OBSCURA",
            kill_switch="BROWSER_OBSCURA_KILL",
        )

    async def test_unconfigured_posthog_leaves_the_kill_switch_off(
        self, stored_user: AsyncMock, no_client: None, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True

    async def test_an_unset_kill_switch_is_off(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        _posthog_serves(mock_client, {"BROWSER_OBSCURA_KILL": False})

        assert await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID) is True
        assert _queried_keys(mock_client) == ["BROWSER_OBSCURA_KILL"]

    async def test_an_internal_flag_has_no_kill_switch(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        _posthog_serves(mock_client, {"CODE_MODE_KILL": True, "CODE_MODE": True})

        assert await is_enabled(FeatureFlag.CODE_MODE, USER_ID) is True
        assert _queried_keys(mock_client) == ["CODE_MODE"]

    def test_every_user_flag_derives_a_kill_key_no_flag_already_uses(self) -> None:
        kill_keys = {
            kill_switch_key(flag) for flag, spec in FEATURE_FLAGS.items() if spec.user_toggle
        }
        assert kill_switch_key(FeatureFlag.BROWSER_OBSCURA) == "BROWSER_OBSCURA_KILL"
        assert kill_keys.isdisjoint({flag.value for flag in FeatureFlag})

    async def test_a_kill_engaged_mid_day_is_not_deduped_into_the_earlier_choice_event(
        self, stored_user: AsyncMock, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        stored_user.return_value = _user_with_choices({"BROWSER_OBSCURA": True})
        _posthog_serves(mock_client, {})
        await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID)
        _posthog_serves(mock_client, {"BROWSER_OBSCURA_KILL": True})
        await is_enabled(FeatureFlag.BROWSER_OBSCURA, USER_ID)

        choice_key, killed_key = (call.kwargs["dedupe_key"] for call in evaluated.call_args_list)
        assert choice_key != killed_key


class TestRetiredChoices:
    def test_a_stored_key_for_a_removed_flag_does_not_fail_the_user_read(self) -> None:
        user = _user_with_choices({"BROWSER_OBSCURA": True, "SOME_RETIRED_FLAG": True})
        assert user.feature_flags == {FeatureFlag.BROWSER_OBSCURA: True}
