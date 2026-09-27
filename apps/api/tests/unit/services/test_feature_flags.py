"""Unit tests for app/services/feature_flags.py."""

from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import CommonSettings, ProductionSettings, settings as app_settings
from app.services.analytics_service import AnalyticsEvents
from app.services.feature_flags import (
    FEATURE_FLAG_DESCRIPTIONS,
    FeatureFlag,
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
    async def test_is_code_mode_enabled_off_when_setting_off(
        self, monkeypatch: pytest.MonkeyPatch, no_client: None
    ) -> None:
        monkeypatch.setattr(app_settings, "ENABLE_CODE_MODE", False)
        assert await is_code_mode_enabled("u1") is False

    async def test_is_code_mode_enabled_live(
        self, mock_client: MagicMock, evaluated: MagicMock
    ) -> None:
        mock_client.get_feature_flag.return_value = True
        assert await is_code_mode_enabled("u1") is True
        mock_client.get_feature_flag.assert_called_once_with("CODE_MODE", "u1")

    async def test_is_hil_ledger_enabled_on_when_setting_on(
        self, monkeypatch: pytest.MonkeyPatch, no_client: None
    ) -> None:
        monkeypatch.setattr(app_settings, "ENABLE_HIL_LEDGER", True)
        assert await is_hil_ledger_enabled("u1") is True

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
    def test_every_flag_has_a_description(self) -> None:
        assert set(FEATURE_FLAG_DESCRIPTIONS) == set(FeatureFlag)

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


class TestShippedDefaults:
    @pytest.mark.parametrize("setting", ["ENABLE_HIL_LEDGER", "ENABLE_CODE_MODE"])
    @pytest.mark.parametrize("settings_class", [CommonSettings, ProductionSettings])
    def test_ships_on(self, setting: str, settings_class: type[CommonSettings]) -> None:
        assert settings_class.model_fields[setting].default is True


class TestEveryFlagFailsOpenToItsOwnSetting:
    def test_every_flag_has_a_kill_switch(self) -> None:
        assert set(FLAG_KILL_SWITCHES) == set(FeatureFlag)

    @pytest.mark.parametrize("flag", list(FeatureFlag), ids=lambda flag: flag.value)
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
