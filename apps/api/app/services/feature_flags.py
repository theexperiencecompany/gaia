"""Per-user feature flags backed by PostHog, with env defaults.

env/Infisical values are read once at boot (get_settings is lru_cached), so a
change needs a redeploy and hits every user at once; PostHog evaluates per
distinct_id at request time, so targeting and rollouts change from the
dashboard with no deploy. The settings value stays the default and
kill-switch: when PostHog is unreachable or unconfigured, evaluation fails
open to it.

Every call evaluates live, no cache: a dashboard flip applies on the next
turn and PostHog's $feature_flag_called stays a complete exposure record. The
single source for flags is this module; call sites never touch PostHog or
settings.ENABLE_* directly. Experiments are built on these flags in the
dashboard, not here.
"""

import asyncio
from datetime import UTC, datetime
from enum import StrEnum

from posthog import Posthog

from app.config.settings import settings
from app.constants.analytics import POSTHOG_PROVIDER_KEY
from app.core.lazy_loader import providers
from app.services.analytics_service import AnalyticsEvents, capture_event
from shared.py.wide_events import log


class FeatureFlag(StrEnum):
    """PostHog flag keys GAIA evaluates; member name is the code handle, value the dashboard key."""

    COMMS_OPENUI = "COMMS_OPENUI"
    CODE_MODE = "CODE_MODE"
    HIL_LEDGER = "HIL_LEDGER"
    HIL_JEV_JUDGE = "HIL_JEV_JUDGE"
    HIL_JEV_REPLY = "HIL_JEV_REPLY"


# Human description per flag, kept next to the key so the dashboard setup and
# the code cannot drift apart.
FEATURE_FLAG_DESCRIPTIONS: dict[FeatureFlag, str] = {
    FeatureFlag.COMMS_OPENUI: (
        "Include the OpenUI component reference in the comms prompt on "
        "renderable channels; off serves the markdown fallback."
    ),
    FeatureFlag.CODE_MODE: (
        "Bash runs seed the `gaia.execute` client and mint a per-invocation "
        "token; off runs bash with no GAIA_EXECUTE_* env. On by default "
        "(see ENABLE_CODE_MODE)."
    ),
    FeatureFlag.HIL_LEDGER: (
        "Gated calls register PENDING in the approval ledger and return "
        "instead of parking the run; off keeps the interrupt barrier. On by "
        "default (see ENABLE_HIL_LEDGER)."
    ),
    FeatureFlag.HIL_JEV_JUDGE: (
        "Auto mode classifies with the JEV choice judge first, falling back "
        "to the LLM intent judge on transport failure; off keeps the LLM judge."
        " On by default (see ENABLE_HIL_JEV_JUDGE)."
    ),
    FeatureFlag.HIL_JEV_REPLY: (
        "A bot user's chat reply to pending approvals is classified by the JEV "
        "reply classifier first, falling back to the LLM classifier on transport "
        "failure; off keeps the LLM classifier. On by default (see ENABLE_HIL_JEV_REPLY)."
    ),
}


def _default(flag: FeatureFlag) -> bool:
    """Return the env default and kill-switch for the flag, read at call time so tests can override settings."""
    match flag:
        case FeatureFlag.COMMS_OPENUI:
            return bool(settings.ENABLE_COMMS_OPENUI)
        case FeatureFlag.CODE_MODE:
            return bool(settings.ENABLE_CODE_MODE)
        case FeatureFlag.HIL_LEDGER:
            return bool(settings.ENABLE_HIL_LEDGER)
        case FeatureFlag.HIL_JEV_JUDGE:
            return bool(settings.ENABLE_HIL_JEV_JUDGE)
        case FeatureFlag.HIL_JEV_REPLY:
            return bool(settings.ENABLE_HIL_JEV_REPLY)


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


async def is_enabled(flag: FeatureFlag, user_id: str | None, default: bool | None = None) -> bool:
    """Evaluate the flag for a user, live on every call, failing open to the default.

    No user means no evaluation and no I/O. The sync SDK call runs in a worker
    thread. Successful evaluations emit no event from us (the SDK auto-emits
    $feature_flag_called); feature_flag:evaluated covers only the fallback paths
    so those users still count in the denominator.
    """
    fallback = _default(flag) if default is None else default
    if not user_id:
        return fallback

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


def _track_evaluation(
    user_id: str, flag: FeatureFlag, enabled: bool, fallback_reason: str | None
) -> None:
    """Emit one fallback event per user/flag/day, for paths the SDK never sees.

    Best-effort and enqueue-only so telemetry never breaks or slows a turn; the
    per-day dedupe key collapses repeats instead of double-counting.
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
                f"feature-flag-evaluated:{flag.value}:{user_id}:"
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
