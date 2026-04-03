"""Unit tests for rate limiting configuration.

Tests cover:
- RateLimitPeriod enum values
- RateLimitConfig defaults and custom values
- FeatureInfo model
- TieredRateLimits model with defaults
- FEATURE_LIMITS dictionary completeness and structure
- get_feature_limits: known and unknown feature keys
- get_limits_for_plan: free vs pro plan retrieval
- get_reset_time: daily and monthly boundary calculations
- get_time_window_key: daily and monthly key formats
- get_feature_info: known and unknown features
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.config.rate_limits import (
    FEATURE_LIMITS,
    FeatureInfo,
    RateLimitConfig,
    RateLimitPeriod,
    TieredRateLimits,
    get_feature_info,
    get_feature_limits,
    get_limits_for_plan,
    get_reset_time,
    get_time_window_key,
)
from app.models.payment_models import PlanType


# ---------------------------------------------------------------------------
# Tests: RateLimitPeriod
# ---------------------------------------------------------------------------


class TestRateLimitPeriod:
    """Tests for the RateLimitPeriod enum."""

    def test_day_value(self) -> None:
        assert RateLimitPeriod.DAY == "day"
        assert RateLimitPeriod.DAY.value == "day"

    def test_month_value(self) -> None:
        assert RateLimitPeriod.MONTH == "month"
        assert RateLimitPeriod.MONTH.value == "month"

    def test_is_string_enum(self) -> None:
        assert isinstance(RateLimitPeriod.DAY, str)
        assert isinstance(RateLimitPeriod.MONTH, str)

    def test_only_two_members(self) -> None:
        assert len(RateLimitPeriod) == 2


# ---------------------------------------------------------------------------
# Tests: RateLimitConfig
# ---------------------------------------------------------------------------


class TestRateLimitConfig:
    """Tests for the RateLimitConfig model."""

    def test_defaults_are_zero(self) -> None:
        config = RateLimitConfig()
        assert config.day == 0
        assert config.month == 0

    def test_custom_values(self) -> None:
        config = RateLimitConfig(day=100, month=3000)
        assert config.day == 100
        assert config.month == 3000

    def test_partial_override(self) -> None:
        config = RateLimitConfig(day=50)
        assert config.day == 50
        assert config.month == 0

    def test_is_pydantic_model(self) -> None:
        config = RateLimitConfig(day=1, month=2)
        data = config.model_dump()
        assert data == {"day": 1, "month": 2}


# ---------------------------------------------------------------------------
# Tests: FeatureInfo
# ---------------------------------------------------------------------------


class TestFeatureInfo:
    """Tests for the FeatureInfo model."""

    def test_construction(self) -> None:
        info = FeatureInfo(title="Test Feature", description="A test feature.")
        assert info.title == "Test Feature"
        assert info.description == "A test feature."

    def test_serialization(self) -> None:
        info = FeatureInfo(title="T", description="D")
        data = info.model_dump()
        assert data == {"title": "T", "description": "D"}


# ---------------------------------------------------------------------------
# Tests: TieredRateLimits
# ---------------------------------------------------------------------------


class TestTieredRateLimits:
    """Tests for the TieredRateLimits model."""

    def test_defaults_are_zero_configs(self) -> None:
        limits = TieredRateLimits(
            info=FeatureInfo(title="Test", description="Test feature"),
        )
        assert limits.free.day == 0
        assert limits.free.month == 0
        assert limits.pro.day == 0
        assert limits.pro.month == 0

    def test_custom_free_and_pro(self) -> None:
        limits = TieredRateLimits(
            free=RateLimitConfig(day=10, month=100),
            pro=RateLimitConfig(day=100, month=1000),
            info=FeatureInfo(title="Feature", description="Desc"),
        )
        assert limits.free.day == 10
        assert limits.free.month == 100
        assert limits.pro.day == 100
        assert limits.pro.month == 1000

    def test_info_is_required(self) -> None:
        with pytest.raises(Exception):
            TieredRateLimits()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Tests: FEATURE_LIMITS dictionary
# ---------------------------------------------------------------------------


class TestFeatureLimits:
    """Tests for the FEATURE_LIMITS configuration dictionary."""

    # All feature keys that should be present
    EXPECTED_FEATURES = [
        "chat_messages",
        "file_upload",
        "file_analysis",
        "skill_operations",
        "generate_image",
        "deep_research",
        "document_generation",
        "web_search",
        "webpage_fetch",
        "workflow_operations",
        "trigger_workflow_executions",
        "goal_tracking",
        "todo_operations",
        "calendar_management",
        "reminder_operations",
        "mail_actions",
        "notes",
        "memory",
        "vfs_write",
        "vfs_cmd",
        "flowchart_creation",
        "code_execution",
        "weather_checks",
        "notification_operations",
        "integration_publish",
        "integration_clone",
    ]

    def test_all_expected_features_present(self) -> None:
        for feature in self.EXPECTED_FEATURES:
            assert feature in FEATURE_LIMITS, f"Missing feature: {feature}"

    def test_no_unexpected_features(self) -> None:
        for feature in FEATURE_LIMITS:
            assert feature in self.EXPECTED_FEATURES, f"Unexpected feature: {feature}"

    def test_all_features_have_valid_structure(self) -> None:
        for key, limits in FEATURE_LIMITS.items():
            assert isinstance(limits, TieredRateLimits), (
                f"{key} is not TieredRateLimits"
            )
            assert isinstance(limits.free, RateLimitConfig), (
                f"{key}.free is not RateLimitConfig"
            )
            assert isinstance(limits.pro, RateLimitConfig), (
                f"{key}.pro is not RateLimitConfig"
            )
            assert isinstance(limits.info, FeatureInfo), (
                f"{key}.info is not FeatureInfo"
            )

    def test_pro_limits_gte_free_limits(self) -> None:
        """Pro plan should always have limits >= free plan."""
        for key, limits in FEATURE_LIMITS.items():
            assert limits.pro.day >= limits.free.day, (
                f"{key}: pro day ({limits.pro.day}) < free day ({limits.free.day})"
            )
            assert limits.pro.month >= limits.free.month, (
                f"{key}: pro month ({limits.pro.month}) < free month ({limits.free.month})"
            )

    def test_monthly_limits_gte_daily_limits(self) -> None:
        """Monthly limits should be >= daily limits for both tiers."""
        for key, limits in FEATURE_LIMITS.items():
            assert limits.free.month >= limits.free.day, (
                f"{key}: free month ({limits.free.month}) < free day ({limits.free.day})"
            )
            assert limits.pro.month >= limits.pro.day, (
                f"{key}: pro month ({limits.pro.month}) < pro day ({limits.pro.day})"
            )

    def test_all_features_have_nonempty_info(self) -> None:
        for key, limits in FEATURE_LIMITS.items():
            assert limits.info.title, f"{key} has empty title"
            assert limits.info.description, f"{key} has empty description"

    def test_free_limits_are_positive(self) -> None:
        """All features should have at least some free tier allowance."""
        for key, limits in FEATURE_LIMITS.items():
            assert limits.free.day > 0, f"{key}: free day is 0"
            assert limits.free.month > 0, f"{key}: free month is 0"

    def test_specific_chat_messages_limits(self) -> None:
        chat = FEATURE_LIMITS["chat_messages"]
        assert chat.free.day == 200
        assert chat.free.month == 5000
        assert chat.pro.day == 3000
        assert chat.pro.month == 60000

    def test_specific_generate_image_limits(self) -> None:
        img = FEATURE_LIMITS["generate_image"]
        assert img.free.day == 1
        assert img.free.month == 2
        assert img.pro.day == 45
        assert img.pro.month == 1350

    def test_specific_deep_research_limits(self) -> None:
        dr = FEATURE_LIMITS["deep_research"]
        assert dr.free.day == 2
        assert dr.free.month == 10
        assert dr.pro.day == 20
        assert dr.pro.month == 600


# ---------------------------------------------------------------------------
# Tests: get_feature_limits
# ---------------------------------------------------------------------------


class TestGetFeatureLimits:
    """Tests for the get_feature_limits function."""

    def test_known_feature(self) -> None:
        result = get_feature_limits("chat_messages")
        assert result is FEATURE_LIMITS["chat_messages"]

    def test_unknown_feature_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature key"):
            get_feature_limits("nonexistent_feature")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature key"):
            get_feature_limits("")

    def test_returns_same_object(self) -> None:
        """Should return the same TieredRateLimits instance from the dict."""
        a = get_feature_limits("web_search")
        b = get_feature_limits("web_search")
        assert a is b


# ---------------------------------------------------------------------------
# Tests: get_limits_for_plan
# ---------------------------------------------------------------------------


class TestGetLimitsForPlan:
    """Tests for get_limits_for_plan — tier-based limit retrieval."""

    def test_free_plan_returns_free_limits(self) -> None:
        result = get_limits_for_plan("chat_messages", PlanType.FREE)
        expected = FEATURE_LIMITS["chat_messages"].free
        assert result is expected

    def test_pro_plan_returns_pro_limits(self) -> None:
        result = get_limits_for_plan("chat_messages", PlanType.PRO)
        expected = FEATURE_LIMITS["chat_messages"].pro
        assert result is expected

    def test_free_plan_values_for_generate_image(self) -> None:
        result = get_limits_for_plan("generate_image", PlanType.FREE)
        assert result.day == 1
        assert result.month == 2

    def test_pro_plan_values_for_generate_image(self) -> None:
        result = get_limits_for_plan("generate_image", PlanType.PRO)
        assert result.day == 45
        assert result.month == 1350

    def test_unknown_feature_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown feature key"):
            get_limits_for_plan("does_not_exist", PlanType.FREE)

    def test_all_features_for_both_plans(self) -> None:
        """Every feature should be retrievable for both FREE and PRO."""
        for feature_key in FEATURE_LIMITS:
            free_result = get_limits_for_plan(feature_key, PlanType.FREE)
            pro_result = get_limits_for_plan(feature_key, PlanType.PRO)
            assert isinstance(free_result, RateLimitConfig)
            assert isinstance(pro_result, RateLimitConfig)


# ---------------------------------------------------------------------------
# Tests: get_reset_time
# ---------------------------------------------------------------------------


class TestGetResetTime:
    """Tests for get_reset_time — daily and monthly reset boundary calculation."""

    def test_daily_reset_is_next_midnight_utc(self) -> None:
        fake_now = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 3, 16, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.DAY)

        assert result == expected

    def test_monthly_reset_is_first_of_next_month(self) -> None:
        fake_now = datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 4, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.MONTH)

        assert result == expected

    def test_monthly_reset_december_rolls_to_january(self) -> None:
        fake_now = datetime(2026, 12, 25, 18, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2027, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.MONTH)

        assert result == expected

    def test_daily_reset_at_midnight_returns_next_day(self) -> None:
        """If called exactly at midnight, the reset should still be the next midnight."""
        fake_now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 6, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.DAY)

        assert result == expected

    def test_monthly_reset_on_first_returns_next_month(self) -> None:
        fake_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        expected = datetime(2026, 2, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.MONTH)

        assert result == expected

    def test_daily_reset_last_day_of_month(self) -> None:
        fake_now = datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc)
        expected = datetime(2026, 3, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            result = get_reset_time(RateLimitPeriod.DAY)

        assert result == expected

    def test_reset_time_is_in_the_future(self) -> None:
        """Reset time should always be in the future."""
        for period in RateLimitPeriod:
            result = get_reset_time(period)
            assert result > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Tests: get_time_window_key
# ---------------------------------------------------------------------------


class TestGetTimeWindowKey:
    """Tests for get_time_window_key — Redis key formatting."""

    def test_daily_key_format(self) -> None:
        fake_now = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = get_time_window_key(RateLimitPeriod.DAY)

        assert result == "20260315"

    def test_monthly_key_format(self) -> None:
        fake_now = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = get_time_window_key(RateLimitPeriod.MONTH)

        assert result == "202603"

    def test_daily_key_single_digit_month_and_day(self) -> None:
        fake_now = datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = get_time_window_key(RateLimitPeriod.DAY)

        assert result == "20260105"

    def test_monthly_key_december(self) -> None:
        fake_now = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = get_time_window_key(RateLimitPeriod.MONTH)

        assert result == "202612"

    def test_daily_key_changes_at_midnight(self) -> None:
        before_midnight = datetime(2026, 6, 15, 23, 59, 59, tzinfo=timezone.utc)
        after_midnight = datetime(2026, 6, 16, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = before_midnight
            key_before = get_time_window_key(RateLimitPeriod.DAY)

            mock_dt.now.return_value = after_midnight
            key_after = get_time_window_key(RateLimitPeriod.DAY)

        assert key_before == "20260615"
        assert key_after == "20260616"
        assert key_before != key_after

    def test_monthly_key_changes_at_month_boundary(self) -> None:
        end_of_march = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)
        start_of_april = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

        with patch("app.config.rate_limits.datetime") as mock_dt:
            mock_dt.now.return_value = end_of_march
            key_march = get_time_window_key(RateLimitPeriod.MONTH)

            mock_dt.now.return_value = start_of_april
            key_april = get_time_window_key(RateLimitPeriod.MONTH)

        assert key_march == "202603"
        assert key_april == "202604"


# ---------------------------------------------------------------------------
# Tests: get_feature_info
# ---------------------------------------------------------------------------


class TestGetFeatureInfo:
    """Tests for the get_feature_info helper."""

    def test_known_feature_returns_configured_info(self) -> None:
        result = get_feature_info("chat_messages")
        assert result["title"] == "Chat Messages"
        assert result["description"] == "Send messages to AI assistants"

    def test_known_feature_returns_dict(self) -> None:
        result = get_feature_info("generate_image")
        assert isinstance(result, dict)
        assert "title" in result
        assert "description" in result

    def test_unknown_feature_returns_generated_info(self) -> None:
        result = get_feature_info("some_unknown_feature")
        assert result["title"] == "Some Unknown Feature"
        assert "some_unknown_feature" in result["description"]

    def test_unknown_feature_title_formatting(self) -> None:
        result = get_feature_info("multi_word_feature_name")
        assert result["title"] == "Multi Word Feature Name"

    def test_unknown_feature_description_format(self) -> None:
        result = get_feature_info("xyz_action")
        assert result["description"] == "Usage for xyz_action"

    def test_all_configured_features_have_info(self) -> None:
        for key in FEATURE_LIMITS:
            result = get_feature_info(key)
            assert result["title"], f"{key} has empty title"
            assert result["description"], f"{key} has empty description"

    def test_deep_research_info(self) -> None:
        result = get_feature_info("deep_research")
        assert result["title"] == "Deep Research"
        assert "research" in result["description"].lower()

    def test_empty_string_feature_returns_generated_info(self) -> None:
        result = get_feature_info("")
        assert isinstance(result, dict)
        assert "title" in result
        assert "description" in result
