"""Account-center workspace sync glue — ``/workspace/account/``.

Materializes the user's account state (subscription, usage, notification
channels, preferences, custom instructions, voice catalog/selection, linked
platforms) as read-only JSON projections on JuiceFS. Each body is rewritten
only when its content changed, so steady-state syncs do zero I/O. The GUIDE
docs under ``account/`` are static system files and are NOT written here.

One source failing (ElevenLabs unreachable, payment provider error) degrades to
skipping THAT file group for the pass — the previous projection stays on disk,
the failure is logged loudly, and the other groups still refresh. One flaky
provider must not blank the user's whole account view.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.constants.account import ACCOUNT_DIR, ACCOUNT_LINKED_ACCOUNTS_DIRNAME
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.account_models import (
    CustomInstructionsProjection,
    LinkedAccountProjection,
    NotificationsProjection,
    PreferencesProjection,
    SubscriptionProjection,
    UsageProjection,
    VoiceCatalogEntry,
    VoiceCatalogProjection,
    VoiceSelectedProjection,
)
from app.models.payment_models import PlanType
from app.services._vfs_scheduler import make_scheduler
from app.services.payments.payment_service import payment_service
from app.services.platform_link_service import Platform, PlatformLinkService
from app.services.storage.account_vfs import AccountFileProjection, materialize_account_files
from app.services.storage.juicefs import _is_mounted, user_workspace_path
from app.services.usage_summary import build_usage_summary
from app.services.voice_service import list_voices
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log


async def build_account_projections(
    user_id: str,
) -> tuple[list[AccountFileProjection], set[str]]:
    """Fetch every account view for ``user_id`` as serialized JSON bodies.

    Returns the projections plus the set of workspace-relative paths whose
    source failed this pass — callers must keep their previous on-disk
    projection instead of pruning it as stale (a stale view beats a missing
    one, and the failure is logged loudly in ``_safe_body``).
    """
    groups: list[tuple[str, Callable[[str], Awaitable[str | None]]]] = [
        ("subscription", _subscription_body),
        ("usage", _usage_body),
        ("notifications", _notifications_body),
        ("preferences", _preferences_body),
        ("custom-instructions", _custom_instructions_body),
        ("voices/catalog", _voice_catalog_body),
        ("voices/selected", _voice_selected_body),
    ]

    # Independent sources — one slow provider must not serialize the rest.
    results = await asyncio.gather(
        *(_safe_body(group, builder, user_id) for group, builder in groups)
    )
    files: list[AccountFileProjection] = []
    failed: set[str] = set()
    for (group, _), body in zip(groups, results):
        if body is None:
            failed.add(f"{ACCOUNT_DIR}/{group}.json")
            continue
        files.append({"id": group, "path": f"{ACCOUNT_DIR}/{group}.json", "body": body})

    linked, linked_failed_paths = await _safe_linked_files(user_id)
    files.extend(linked)
    failed.update(linked_failed_paths)
    return files, failed


async def sync_account_files(user_id: str) -> int:
    """Materialize the user's account projections to JuiceFS.

    Returns the number of bodies rewritten; ``0`` means the mount is missing
    (native dev) or nothing changed since the last pass.
    """
    if not _is_mounted():
        return 0
    files, failed = await build_account_projections(user_id)
    return await asyncio.to_thread(
        materialize_account_files, user_workspace_path(user_id), files, failed
    )


# Fire-and-forget wrapper for settings/linking/billing write paths.
schedule_account_sync = make_scheduler(sync_account_files, log_name="account_vfs")


# --- source builders --------------------------------------------------------
#
# Each body builder returns the serialized JSON for its file, or None when the
# source has nothing to say yet. A raised error skips that group for the pass
# (logged in _safe_body) without touching the other files.


async def _safe_body(
    group: str,
    builder: Callable[[str], Awaitable[str | None]],
    user_id: str,
) -> str | None:
    try:
        return await builder(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.STORAGE} account projection failed — group skipped this pass",
            group=group,
            user={"id": user_id},
            error_type=type(e).__name__,
            error=str(e),
        )
        return None


async def _safe_linked_files(
    user_id: str,
) -> tuple[list[AccountFileProjection], set[str]]:
    """Linked-platform projections, plus the paths to preserve from the prune.

    On failure every platform file is preserved: a provider error must not look
    like the user unplugged everything.
    """
    try:
        return await _linked_account_bodies(user_id), set()
    except Exception as e:
        stale = {
            f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{p.value}.json" for p in Platform
        }
        log.error(
            f"{LogTag.STORAGE} account projection failed — linked accounts skipped this pass",
            user={"id": user_id},
            error_type=type(e).__name__,
            error=str(e),
            preserved=sorted(stale),
        )
        return [], stale


async def _subscription_body(user_id: str) -> str:
    status = await payment_service.get_user_subscription_status(user_id)
    plan_type = (status.plan_type or PlanType.FREE).value
    plan = status.current_plan or {}
    subscription = status.subscription or {}
    projection = SubscriptionProjection(
        plan_type=plan_type,
        plan_name=plan.get("name"),
        price=None
        if not plan.get("amount")
        else f"{plan.get('currency', '')} {plan['amount']} / {plan.get('duration', 'period')}".strip(),
        status=subscription.get("status"),
        cancel_scheduled=bool(subscription.get("cancel_at_next_billing_date")),
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _usage_body(user_id: str) -> str:
    summary = await build_usage_summary(user_id)
    projection = UsageProjection(
        plan_type=summary.plan_type,
        daily=summary.budget.daily,
        monthly=summary.budget.monthly,
        per_request_token_ceiling=summary.budget.per_request_token_ceiling,
        features=summary.features,
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _notifications_body(user_id: str) -> str:
    channels = await fetch_channel_preferences(user_id)
    return NotificationsProjection(channels=channels).model_dump_json(indent=2) + "\n"


async def _preferences_body(user_id: str) -> str:
    preferences = await _onboarding_preferences(user_id)
    user = await user_repository.get(user_id)
    # model_validate, not the constructor: these are raw Mongo blob values and
    # Pydantic is what actually narrows them. A cast() here would only assert
    # the type to mypy while doing nothing at runtime.
    projection = PreferencesProjection.model_validate(
        {
            "response_style": preferences.get("response_style"),
            "timezone": user.timezone if user else None,
        }
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _custom_instructions_body(user_id: str) -> str:
    preferences = await _onboarding_preferences(user_id)
    projection = CustomInstructionsProjection.model_validate(
        {"instructions": preferences.get("custom_instructions")}
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _voice_catalog_body(user_id: str) -> str:
    catalog = await list_voices(user_id)
    projection = VoiceCatalogProjection(
        voices=[
            VoiceCatalogEntry(voice_id=v.voice_id, name=v.name, starred=v.starred)
            for v in catalog.voices
        ]
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _voice_selected_body(user_id: str) -> str:
    catalog = await list_voices(user_id)
    selected = next((v for v in catalog.voices if v.voice_id == catalog.selected_voice_id), None)
    projection = VoiceSelectedProjection(
        voice_id=catalog.selected_voice_id, name=selected.name if selected else None
    )
    return projection.model_dump_json(indent=2) + "\n"


async def _linked_account_bodies(user_id: str) -> list[AccountFileProjection]:
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    files: list[AccountFileProjection] = []
    for platform in Platform:
        entry = linked.get(platform.value)
        projection = LinkedAccountProjection(
            platform=platform.value,
            connected=entry is not None,
            connected_at=entry.get("connectedAt") if entry else None,
            username=entry.get("username") if entry else None,
            display_name=entry.get("displayName") if entry else None,
        )
        files.append(
            {
                "id": f"linked-{platform.value}",
                "path": f"{ACCOUNT_DIR}/{ACCOUNT_LINKED_ACCOUNTS_DIRNAME}/{platform.value}.json",
                "body": projection.model_dump_json(indent=2) + "\n",
            }
        )
    return files


async def _onboarding_preferences(user_id: str) -> dict[str, object]:
    user = await user_repository.get(user_id)
    onboarding = user.onboarding if user else None
    preferences = (onboarding or {}).get("preferences")
    return preferences if isinstance(preferences, dict) else {}


__all__ = [
    "build_account_projections",
    "schedule_account_sync",
    "sync_account_files",
]
