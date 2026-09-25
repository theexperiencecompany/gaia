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
from app.constants.feature_flags import (
    FEATURE_KILLED_FIX,
    FEATURE_KILLED_MESSAGE,
    FEATURE_KILLED_WHY,
    FEATURE_NOT_FOUND_FIX,
    FEATURE_NOT_FOUND_MESSAGE,
    FEATURE_NOT_FOUND_WHY,
    FEATURE_USER_NOT_FOUND_MESSAGE,
    FEATURE_USER_NOT_FOUND_WHY,
)
from app.core.lazy_loader import providers
from app.db.repositories.users import user_repository
from app.schemas.feature_flags import UserFeatureFlagListResponse, UserFeatureFlagResponse
from app.services.analytics_service import AnalyticsEvents, capture_event, identify_user
from app.utils.errors import AppError
from shared.py.wide_events import log


def _answer_enables(answer: object) -> bool:
    """Interpret a flag value PostHog did evaluate: any non-control variant string counts as enabled."""
    if isinstance(answer, str):
        return answer.strip().lower() not in ("", "false", "off", "disabled", "control")
    return bool(answer)


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
    killed: bool = False


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
    if result is None:
        # The SDK swallows transport errors into None, so this is also the unreachable case.
        log.warning(
            "Feature flag kill switch unevaluated, leaving it disengaged",
            flag=flag.value,
            kill_switch=key,
        )
        return False
    return _answer_enables(result)


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

    if result is None:
        _track_evaluation(user_id, flag, fallback, fallback_reason="flag_unevaluated")
        return fallback
    return _answer_enables(result)


async def _resolve(flag: FeatureFlag, user_id: str, fallback: bool) -> _Resolution:
    """Kill switch, then stored choice (user-facing flags only), then PostHog, then the default."""
    user_facing = FEATURE_FLAGS[flag].user_toggle is not None
    if user_facing and await _kill_switch_engaged(flag, user_id):
        _track_evaluation(user_id, flag, False, fallback_reason="killed")
        resolution = _Resolution(enabled=False, killed=True)
    elif user_facing and (choice := await _stored_choice(flag, user_id)) is not None:
        _track_evaluation(user_id, flag, choice, fallback_reason="user_choice")
        resolution = _Resolution(enabled=choice)
    else:
        resolution = _Resolution(enabled=await _posthog_value(flag, user_id, fallback))
    log.set(flags={flag.value: resolution.enabled})
    return resolution


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
            message=FEATURE_NOT_FOUND_MESSAGE,
            why=FEATURE_NOT_FOUND_WHY,
            fix=FEATURE_NOT_FOUND_FIX,
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


async def _user_feature(
    flag: FeatureFlag, toggle: UserToggle, user_id: str
) -> UserFeatureFlagResponse:
    resolution = await _resolve(flag, user_id, FEATURE_FLAGS[flag].default())
    return _feature_response(flag, toggle, resolution)


async def list_user_flags(user_id: str) -> UserFeatureFlagListResponse:
    """List every user-facing flag with the value in effect for this user; internal flags never appear."""
    features = await asyncio.gather(
        *(
            _user_feature(flag, spec.user_toggle, user_id)
            for flag, spec in FEATURE_FLAGS.items()
            if spec.user_toggle is not None
        )
    )
    return UserFeatureFlagListResponse(features=list(features))


async def set_user_flag(user_id: str, key: str, enabled: bool) -> UserFeatureFlagResponse:
    """Store the user's choice for a user-facing flag and record it in PostHog."""
    flag, toggle = _user_facing_flag(key)
    if await _kill_switch_engaged(flag, user_id):
        raise AppError(
            message=FEATURE_KILLED_MESSAGE,
            why=FEATURE_KILLED_WHY,
            fix=FEATURE_KILLED_FIX,
            status_code=409,
            code=FEATURE_KILLED,
            meta={"flag": flag.value},
        )
    if not await user_repository.set_feature_flag(user_id, flag, enabled):
        raise AppError(
            message=FEATURE_USER_NOT_FOUND_MESSAGE,
            why=FEATURE_USER_NOT_FOUND_WHY,
            status_code=404,
            meta={"user_id": user_id},
        )
    capture_event(
        user_id, AnalyticsEvents.FEATURE_TOGGLED, {"flag": flag.value, "enabled": enabled}
    )
    identify_user(
        user_id, {f"{FEATURE_CHOICE_PERSON_PROPERTY_PREFIX}{flag.value.lower()}": enabled}
    )
    return _feature_response(flag, toggle, _Resolution(enabled=enabled))


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
