"""Per-user feature flag evaluation: the user's own choice, then PostHog, then the env default.

Flags are declared once, in app/config/feature_flags.py. env/Infisical values
are read once at boot, so a change there needs a redeploy and hits every user;
PostHog evaluates per distinct_id at request time, so targeting and rollouts
change from the dashboard with no deploy. The settings value stays the default
and kill-switch: when PostHog is unreachable or unconfigured, evaluation fails
open to it. A user-facing flag also honours the choice the user stored in
Settings, ahead of the rollout; an internal flag never reads one. Ahead of
both sits its kill switch, which only PostHog can engage: when PostHog cannot
answer, the switch stays off and the user's choice stands.

Every call evaluates live, with no cache of the result: a dashboard flip
applies on the next turn and PostHog's $feature_flag_called stays a complete
exposure record. Call sites never touch PostHog or settings.ENABLE_* directly.
"""

import asyncio
from datetime import UTC, datetime
from typing import NamedTuple

from posthog import Posthog

from app.config.feature_flags import (
    FEATURE_FLAGS,
    KILL_SWITCH_REASON,
    FeatureFlag,
    UserToggle,
    kill_switch_key,
)
from app.constants.analytics import FEATURE_CHOICE_PERSON_PROPERTY_PREFIX, POSTHOG_PROVIDER_KEY
from app.constants.error_codes import FEATURE_KILLED
from app.core.lazy_loader import providers
from app.db.repositories.users import user_repository
from app.schemas.feature_flags import UserFeatureFlagListResponse, UserFeatureFlagResponse
from app.services.analytics_service import AnalyticsEvents, capture_event, identify_user
from app.utils.errors import AppError
from shared.py.wide_events import log


def _coerce_result(result: object, default: bool) -> bool:
    """Interpret a PostHog flag value against a default.

    None means unevaluated (no targeting matched, or an upstream error) and
    falls back to the default; any non-control variant string counts as enabled.
    """
    if result is None:
        return default
    if isinstance(result, bool):
        return result
    if isinstance(result, str):
        return result.strip().lower() not in ("", "false", "off", "disabled", "control")
    return bool(result)


def _get_posthog_client() -> Posthog | None:
    """Return the shared PostHog client, or None when unconfigured."""
    try:
        if not providers.is_available(POSTHOG_PROVIDER_KEY):
            log.debug("PostHog client not available, flag falls back to default")
            return None
        client: Posthog | None = providers.get(POSTHOG_PROVIDER_KEY)
        return client
    except Exception as e:
        log.debug(
            "PostHog provider lookup failed, flag falls back to default",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def _stored_choice(flag: FeatureFlag, user_id: str) -> bool | None:
    """Return the user's own choice for the flag, or None when they never made one."""
    user = await user_repository.get(user_id)
    if user is None or user.feature_flags is None:
        return None
    return user.feature_flags.get(flag)


class _Resolution(NamedTuple):
    enabled: bool
    killed: bool


async def _kill_switch_engaged(flag: FeatureFlag, user_id: str) -> bool:
    """Whether ops forced the flag off; an unreachable or unconfigured PostHog never engages it."""
    client = _get_posthog_client()
    if client is None:
        return False
    key = kill_switch_key(flag)
    try:
        result = await asyncio.to_thread(client.get_feature_flag, key, user_id)
    except Exception as e:
        log.warning(
            "Feature flag kill switch check failed, leaving it disengaged",
            flag=flag.value,
            kill_switch=key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return _coerce_result(result, False)


async def _posthog_value(flag: FeatureFlag, user_id: str, fallback: bool) -> bool:
    client = _get_posthog_client()
    if client is None:
        _track_evaluation(user_id, flag, fallback, fallback_reason="posthog_unconfigured")
        return fallback

    try:
        result = await asyncio.to_thread(client.get_feature_flag, flag.value, user_id)
    except Exception as e:
        log.warning(
            "Feature flag evaluation failed, falling back to default",
            flag=flag.value,
            error=str(e),
            error_type=type(e).__name__,
        )
        _track_evaluation(user_id, flag, fallback, fallback_reason="evaluation_error")
        return fallback

    evaluated = result is not None
    enabled = _coerce_result(result, fallback)
    log.set(flags={flag.value: enabled})
    if not evaluated:
        _track_evaluation(user_id, flag, enabled, fallback_reason="flag_unevaluated")
    return enabled


async def _resolve(flag: FeatureFlag, user_id: str, fallback: bool) -> _Resolution:
    """Kill switch, then stored choice (user-facing flags only), then PostHog, then the default."""
    if FEATURE_FLAGS[flag].user_toggle is not None:
        if await _kill_switch_engaged(flag, user_id):
            log.set(flags={flag.value: False})
            _track_evaluation(user_id, flag, False, fallback_reason="killed")
            return _Resolution(enabled=False, killed=True)
        choice = await _stored_choice(flag, user_id)
        if choice is not None:
            log.set(flags={flag.value: choice})
            _track_evaluation(user_id, flag, choice, fallback_reason="user_choice")
            return _Resolution(enabled=choice, killed=False)
    return _Resolution(enabled=await _posthog_value(flag, user_id, fallback), killed=False)


async def is_enabled(flag: FeatureFlag, user_id: str | None, default: bool | None = None) -> bool:
    """Evaluate the flag for a user, live on every call: kill switch, stored choice, PostHog, default.

    No user means no evaluation and no I/O; only a user-facing flag has a kill
    switch and a stored choice. PostHog runs in a worker thread and fails open.
    The SDK auto-emits $feature_flag_called on success; feature_flag:evaluated
    covers every other path so those users still count in the denominator.
    """
    spec = FEATURE_FLAGS[flag]
    fallback = spec.default() if default is None else default
    if not user_id:
        return fallback
    return (await _resolve(flag, user_id, fallback)).enabled


def _track_evaluation(
    user_id: str, flag: FeatureFlag, enabled: bool, fallback_reason: str | None
) -> None:
    """Emit one event per user/flag/reason/day, for paths the SDK never sees.

    Best-effort and enqueue-only so telemetry never breaks or slows a turn; the
    per-day dedupe key collapses repeats, and carries the reason so a kill
    engaged mid-day still shows up the same day.
    """
    try:
        capture_event(
            user_id,
            AnalyticsEvents.FEATURE_FLAG_EVALUATED,
            {
                "flag": flag.value,
                "enabled": enabled,
                **({"fallback_reason": fallback_reason} if fallback_reason else {}),
            },
            dedupe_key=(
                f"feature-flag-evaluated:{flag.value}:{user_id}:{fallback_reason}:"
                f"{datetime.now(UTC).date().isoformat()}"
            ),
        )
    except Exception as e:
        log.debug(
            "Feature flag evaluation event skipped",
            flag=flag.value,
            error=str(e),
            error_type=type(e).__name__,
        )


def _user_facing_flag(key: str) -> tuple[FeatureFlag, UserToggle]:
    """Resolve a flag key a client sent; unknown and internal keys are the same 404."""
    flag = next((known for known in FeatureFlag if known.value == key), None)
    toggle = FEATURE_FLAGS[flag].user_toggle if flag is not None else None
    if flag is None or toggle is None:
        raise AppError(
            message="Feature not found",
            why="no user-facing feature flag has this key",
            fix="List the toggleable features with GET /api/v1/features",
            status_code=404,
            meta={"flag": key},
        )
    return flag, toggle


def _feature_response(
    flag: FeatureFlag, toggle: UserToggle, resolution: _Resolution
) -> UserFeatureFlagResponse:
    return UserFeatureFlagResponse(
        key=flag.value,
        label=toggle.label,
        description=toggle.description,
        stage=toggle.stage,
        enabled=resolution.enabled,
        available=not resolution.killed,
        unavailable_reason=KILL_SWITCH_REASON if resolution.killed else None,
    )


async def list_user_flags(user_id: str) -> UserFeatureFlagListResponse:
    """List every user-facing flag with the value in effect for this user; internal flags never appear."""
    toggles = [
        (flag, spec.user_toggle, spec.default())
        for flag, spec in FEATURE_FLAGS.items()
        if spec.user_toggle is not None
    ]
    resolutions = await asyncio.gather(
        *(_resolve(flag, user_id, default) for flag, _, default in toggles)
    )
    return UserFeatureFlagListResponse(
        features=[
            _feature_response(flag, toggle, resolution)
            for (flag, toggle, _), resolution in zip(toggles, resolutions, strict=True)
        ]
    )


async def set_user_flag(user_id: str, key: str, enabled: bool) -> UserFeatureFlagResponse:
    """Store the user's choice for a user-facing flag and record it in PostHog."""
    flag, toggle = _user_facing_flag(key)
    if await _kill_switch_engaged(flag, user_id):
        raise AppError(
            message="This feature is paused for everyone right now",
            why="the flag's kill switch is engaged in PostHog, which overrides every choice",
            fix="Try again once the feature is back; your current choice is kept",
            status_code=409,
            code=FEATURE_KILLED,
            meta={"flag": flag.value},
        )
    if not await user_repository.set_feature_flag(user_id, flag, enabled):
        raise AppError(
            message="User not found",
            why="no user document matches the authenticated session's id",
            status_code=404,
            meta={"user_id": user_id},
        )
    capture_event(
        user_id, AnalyticsEvents.FEATURE_TOGGLED, {"flag": flag.value, "enabled": enabled}
    )
    identify_user(
        user_id, {f"{FEATURE_CHOICE_PERSON_PROPERTY_PREFIX}{flag.value.lower()}": enabled}
    )
    return _feature_response(flag, toggle, _Resolution(enabled=enabled, killed=False))


async def is_code_mode_enabled(user_id: str | None) -> bool:
    """Whether the user's bash runs get the gaia.execute client and a per-invocation token; off runs with no GAIA_EXECUTE_* env."""
    return await is_enabled(FeatureFlag.CODE_MODE, user_id)


async def is_hil_ledger_enabled(user_id: str | None) -> bool:
    """Whether the user's gated calls register PENDING in the approval ledger instead of parking the run; off keeps the barrier."""
    return await is_enabled(FeatureFlag.HIL_LEDGER, user_id)


async def is_jev_judge_enabled(user_id: str | None) -> bool:
    """Whether the user's auto mode classifies with JEV first (LLM fallback on transport failure); off keeps the LLM judge."""
    return await is_enabled(FeatureFlag.HIL_JEV_JUDGE, user_id)


async def is_jev_reply_enabled(user_id: str | None) -> bool:
    """Whether the user's chat replies to pending approvals are classified by JEV first (LLM fallback on transport failure)."""
    return await is_enabled(FeatureFlag.HIL_JEV_REPLY, user_id)
