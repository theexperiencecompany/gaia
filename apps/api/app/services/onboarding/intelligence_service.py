"""
Gmail personalization pipeline — a DAG that runs once, when a user connects Gmail.

Every node is an asyncio.Task that awaits its specific upstream futures and
emits its own stage event the moment it completes. The frontend consumes these
events independently and paces the visual reveal. There are no phases, no
progress percentages, and no false dependencies.

  fetch_inbox → triage ──┐
       ↘ memory ingest   ├→ persist → social profiles → holo card → announce
  writing_style ─────────┘

The pipeline creates nothing the user has to clean up: no todos, no workflows,
no generated first message. Its output is memories, a learned writing style, a
triage summary, social profiles and the holo card — the reward for connecting
Gmail. System workflows are provisioned by the OAuth connect handler itself.
"""

import asyncio
from dataclasses import dataclass, field, replace
from enum import Enum
import time
from typing import Any

from app.agents.memory.email_processor import (
    OnboardingFetchOptions,
    fetch_emails_for_onboarding,
)
from app.config.settings import settings
from app.constants.email import ONBOARDING_EMAIL_SCAN_LIMIT
from app.constants.log_tags import LogTag
from app.constants.notifications import MEMORY_SETTINGS_URL
from app.constants.onboarding import TRIAGE_EARLY_THRESHOLD
from app.core.websocket_manager import websocket_manager
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.onboarding_models import (
    ClarifyAnswerRecord,
    InboxTriage,
    PersistedTriageSummary,
    SocialProfile,
    SocialProfilesReadyPayload,
    StagePayload,
    StatusTextPayload,
    TriageEmailSummary,
    TriageReadyPayload,
    WritingStyleProfile,
    WritingStyleReadyPayload,
)
from app.models.user_models import PersonalizationBundle, UserDocument
from app.services.composio.composio_service import get_composio_service
from app.services.notification_service import notification_service
from app.services.onboarding import inbox_scan_cache
from app.services.onboarding.inbox_triage_service import triage_inbox
from app.services.onboarding.intelligence_job import personalization_already_ran
from app.services.onboarding.social_profile_service import (
    dedup_profiles_by_platform,
    extract_social_profiles_from_emails,
)
from app.services.onboarding.writing_style_service import learn_writing_style
from app.utils.background_tasks import spawn_background_task
from app.utils.profile_card import (
    generate_holo_card_content,
    generate_profile_card_design,
    get_user_metadata,
)
from app.utils.redis_utils import RedisPoolManager
from app.utils.seeding_utils import seed_holo_card_conversation
from shared.py.wide_events import log

# The public holo-card page. `card_id` in that route is the user's own id — the
# card is shareable the moment its content is saved; there is no publish step.
_HOLO_CARD_PATH = "/profile"

_PERSONALIZATION_NOTIFICATION_TITLE = "Check your memories — I just added a lot"
_MEMORIES_NOTIFICATION_BODY = (
    "I read through your inbox and saved what matters — the people you work with, "
    "how you write, what you're on top of."
)


class OnboardingStage(str, Enum):
    """Stages emitted over WebSocket during Gmail personalization."""

    INBOX_SCANNING = "inbox_scanning"
    WRITING_STYLE_PROGRESS = "writing_style_progress"
    WRITING_STYLE_READY = "writing_style_ready"
    SOCIAL_PROFILES_READY = "social_profiles_ready"
    TRIAGE_ANALYZING = "triage_analyzing"
    TRIAGE_READY = "triage_ready"
    HOLO_READY = "holo_ready"


async def _emit_stage(
    user_id: str,
    stage: OnboardingStage,
    payload: StagePayload | None = None,
) -> None:
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": "onboarding_stage",
                "data": {"stage": stage.value, "payload": payload.to_wire() if payload else {}},
            },
        )
        status_text = payload.status_text if isinstance(payload, StatusTextPayload) else None
        if status_text:
            log.info(
                f"{LogTag.ONBOARDING} stage emitted with status",
                stage_value=stage.value,
                status_text=status_text,
            )
        else:
            log.info(f"{LogTag.ONBOARDING} stage emitted", stage_value=stage.value)
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} Failed to emit stage",
            stage_value=stage.value,
            error=str(e),
            error_type=type(e).__name__,
        )


@dataclass
class InboxScanContext:
    """Shared state between the inbox fetch task and triage (which starts
    as soon as enough emails are buffered)."""

    # Raw Gmail message dicts straight off `fetch_emails_for_onboarding`; the key
    # set varies with the fetch format and the provider's casing (`labelIds` vs
    # `label_ids`), so this is a genuine external-boundary shape (item 8).
    emails: list[dict[str, Any]] = field(default_factory=list)
    first_batch_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class OnboardingContext:
    """Shared per-user context threaded through the personalization helpers."""

    user_id: str
    name: str
    profession: str = ""
    focus: str = ""
    user_email: str | None = None
    triage: InboxTriage | None = None
    writing_style: WritingStyleProfile | None = None
    clarify_answers: list[ClarifyAnswerRecord] = field(default_factory=list)


async def _scan_then_enqueue_memory(user_id: str, ctx: InboxScanContext) -> None:
    """Run the visible inbox scan, then queue durable memory ingestion so it
    runs in parallel with the rest of the DAG and survives later failures.

    Ingestion is queued *after* the scan on purpose: both hit the same Composio
    Gmail capacity, and racing them starves the user-visible scan.
    """
    await _run_inbox_scanning(user_id, ctx)
    try:
        pool = await RedisPoolManager.get_pool()
        await pool.enqueue_job("process_gmail_emails_to_memory", user_id)
        log.info(
            f"{LogTag.ONBOARDING} queued gmail->memory ingestion",
            user_id=user_id,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} failed to queue gmail->memory ingestion",
            user_id=user_id,
            error=str(e)[:200],
            error_type=type(e).__name__,
        )


async def process_onboarding_intelligence(user_id: str) -> None:
    """Gmail personalization DAG. Called as an ARQ background task when a user
    connects Gmail, at most once per user."""
    log.set(user={"id": user_id})
    pipeline_start = time.monotonic()
    log.info(f"{LogTag.ONBOARDING} pipeline start", user_id=user_id, phase="start")

    user = await user_repository.get(user_id)
    if user is None:
        log.error(
            f"{LogTag.ONBOARDING} user not found",
            user_id=user_id,
            outcome="aborted",
            reason="user_not_found",
        )
        return

    onboarding = user.onboarding or {}
    # Re-check at run time, not just at enqueue time: a queued job can outlive a
    # second connect that already completed the pipeline.
    if personalization_already_ran(onboarding):
        log.info(
            f"{LogTag.ONBOARDING} pipeline skipped",
            user_id=user_id,
            outcome="skipped",
            reason="already_ran",
        )
        return

    composio_service = get_composio_service()
    connection_status = await composio_service.check_connection_status(["gmail"], user_id)
    if not connection_status.get("gmail", False):  # pragma: no mutate — default only negated
        log.warning(
            f"{LogTag.ONBOARDING} pipeline aborted — gmail not connected",
            user_id=user_id,
            outcome="aborted",
            reason="no_gmail",
        )
        return

    base_ctx = OnboardingContext(
        user_id=user_id,
        name=user.name or "there",
        profession=(onboarding.get("preferences") or {}).get("profession", "")
        or "",  # pragma: no mutate — `or ""` collapses the default
        focus=onboarding.get("focus", "")
        or "",  # pragma: no mutate — `or ""` collapses the default
        user_email=user.email,
        clarify_answers=onboarding.get("clarify_answers") or [],
    )

    inbox_ctx = InboxScanContext()
    spawn_background_task(_scan_then_enqueue_memory(user_id, inbox_ctx))

    t_gather = time.monotonic()
    triage, writing_style = await asyncio.gather(
        _run_triage(user_id, inbox_ctx, base_ctx.profession, base_ctx.focus),
        _run_writing_style(user_id, base_ctx.profession),
    )
    log.info(
        f"{LogTag.ONBOARDING} critical_path gathered",
        user_id=user_id,
        phase="critical_path_gather",
        duration_s=round(time.monotonic() - t_gather, 2),
    )

    ctx = replace(base_ctx, triage=triage, writing_style=writing_style)
    await _persist_profiles(user_id, writing_style, triage)
    social_profiles = await _run_social_profiles(user_id, ctx.name, ctx.user_email)
    card_ready = await _run_holo_card(ctx, user, social_profiles)

    conversation_id = await _announce_personalization(user_id, card_ready=card_ready)
    await user_repository.mark_gmail_personalization_done(user_id, conversation_id=conversation_id)

    log.info(
        f"{LogTag.ONBOARDING} pipeline done",
        user_id=user_id,
        phase="done",
        writing_style_learned=writing_style is not None,
        triage_important_count=len(triage.important_emails) if triage else 0,
        social_profiles_count=len(social_profiles),
        conversation_seeded=conversation_id is not None,
        outcome=("ok" if conversation_id else "partial"),
        duration_s=round(time.monotonic() - pipeline_start, 2),
    )


async def _run_inbox_scanning(user_id: str, ctx: InboxScanContext) -> None:
    """Stream the inbox into ctx.emails. Sets first_batch_ready once ~100
    emails buffered so triage can start early; sets done when fetch completes."""
    t0 = time.monotonic()

    cached = await inbox_scan_cache.get(user_id, "metadata")
    if cached is not None:
        ctx.emails.extend(cached)
        ctx.first_batch_ready.set()
        ctx.done.set()
        await _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            StatusTextPayload(status_text=f"Loaded {len(cached)} cached emails"),
        )
        log.info(
            f"{LogTag.ONBOARDING} inbox_scanning cache_hit",
            user_id=user_id,
            step="inbox_scanning",
            outcome="ok",
            emails_fetched=len(cached),
            cache_hit=True,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return

    await _emit_stage(
        user_id,
        OnboardingStage.INBOX_SCANNING,
        StatusTextPayload(status_text="Connecting to Gmail"),
    )

    async def _on_batch(current: int, latest_sender: str | None) -> None:
        if not ctx.first_batch_ready.is_set() and current >= TRIAGE_EARLY_THRESHOLD:
            ctx.first_batch_ready.set()
        status_text = (
            f"Fetched {current} emails — {latest_sender}"
            if latest_sender
            else f"Fetched {current} emails"
        )
        await _emit_stage(
            user_id,
            OnboardingStage.INBOX_SCANNING,
            StatusTextPayload(status_text=status_text),
        )

    fetch_ok = False
    try:
        await fetch_emails_for_onboarding(
            user_id,
            months=1,
            max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
            on_batch=_on_batch,
            into=ctx.emails,
        )
        fetch_ok = True
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} inbox_scanning failed",
            user_id=user_id,
            step="inbox_scanning",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
    finally:
        ctx.first_batch_ready.set()
        ctx.done.set()
        if fetch_ok:
            await inbox_scan_cache.put(user_id, "metadata", list(ctx.emails))

    log.info(
        f"{LogTag.ONBOARDING} inbox_scanning done",
        user_id=user_id,
        step="inbox_scanning",
        outcome="ok" if fetch_ok else "failed",
        emails_fetched=len(ctx.emails),
        duration_s=round(time.monotonic() - t0, 2),
    )


async def _run_writing_style(user_id: str, profession: str) -> WritingStyleProfile | None:
    """Learn writing style from the user's last 50 sent emails."""

    async def _on_status(status_text: str) -> None:
        await _emit_stage(
            user_id,
            OnboardingStage.WRITING_STYLE_PROGRESS,
            StatusTextPayload(status_text=status_text),
        )

    t0 = time.monotonic()
    try:
        result = await learn_writing_style(user_id, profession=profession, on_status=_on_status)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} writing_style failed",
            user_id=user_id,
            step="writing_style",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        result = None

    log.info(
        f"{LogTag.ONBOARDING} writing_style done",
        user_id=user_id,
        step="writing_style",
        outcome="ok" if result else "empty",
        learned=result is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )

    await _emit_stage(
        user_id,
        OnboardingStage.WRITING_STYLE_READY,
        WritingStyleReadyPayload(
            style_summary=result.summary if result and result.summary else None,
            example=result.example if result and result.example else None,
        ),
    )
    return result


async def _run_triage(
    user_id: str,
    inbox_ctx: InboxScanContext,
    profession: str,
    focus: str,
) -> InboxTriage | None:
    await inbox_ctx.first_batch_ready.wait()
    emails = list(inbox_ctx.emails)
    if not emails:
        log.info(
            f"{LogTag.ONBOARDING} triage skipped",
            user_id=user_id,
            step="triage",
            outcome="skipped",
            skip_reason="no_emails",
        )
        return None

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_ANALYZING,
        StatusTextPayload(status_text=f"Analyzing {len(emails)} emails"),
    )

    t0 = time.monotonic()
    try:
        result = await triage_inbox(user_id, emails, profession=profession, focus=focus)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} triage failed",
            user_id=user_id,
            step="triage",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        result = None
    log.info(
        f"{LogTag.ONBOARDING} triage done",
        user_id=user_id,
        step="triage",
        outcome="ok" if result else "empty",
        emails_in=len(emails),
        important_count=len(result.important_emails) if result else 0,
        patterns_count=len(result.patterns) if result else 0,
        total_unread=result.total_unread if result else 0,
        duration_s=round(time.monotonic() - t0, 2),
    )

    if result and result.important_emails:
        n = len(result.important_emails)
        await _emit_stage(
            user_id,
            OnboardingStage.TRIAGE_ANALYZING,
            StatusTextPayload(status_text=f"Found {n} important thread{'s' if n != 1 else ''}"),
        )

    await _emit_stage(
        user_id,
        OnboardingStage.TRIAGE_READY,
        TriageReadyPayload(
            total_scanned=result.total_scanned if result else len(emails),
            total_unread=result.total_unread if result else 0,
            summary=result.summary if result else None,
            patterns=result.patterns if result else [],
            important_emails=_important_emails_for_client(result),
        ),
    )
    return result


def _important_emails_for_client(triage: InboxTriage | None) -> list[TriageEmailSummary]:
    """The top few important emails, projected onto the fields the client shows."""
    return [
        TriageEmailSummary(sender=e.sender, subject=e.subject, why_important=e.why_important)
        for e in (triage.important_emails[:5] if triage else [])
    ]


async def _run_social_profiles(
    user_id: str,
    user_name: str,
    user_email: str | None,
) -> list[SocialProfile]:
    """Fetch full email bodies, extract social profiles, persist, and emit
    SOCIAL_PROFILES_READY. Returns the deduped profiles."""
    t0 = time.monotonic()
    profiles: list[SocialProfile] = []
    try:
        emails = await inbox_scan_cache.get(user_id, "full")
        if emails is None:
            emails = await fetch_emails_for_onboarding(
                user_id,
                months=1,
                max_total=ONBOARDING_EMAIL_SCAN_LIMIT,
                options=OnboardingFetchOptions(fmt="full", include_sent=True),
            )
            # Only cache a non-empty fetch. A cached [] is not None, so every later
            # run would skip both the fetch and the extraction and leave the user
            # with no social profiles forever.
            if emails:
                await inbox_scan_cache.put(user_id, "full", emails)

        if emails:
            raw = await extract_social_profiles_from_emails(emails, user_name, user_email)
            raw_count = len(raw)
            profiles = dedup_profiles_by_platform(raw)
            await _persist_social_profiles(user_id, profiles)
            log.info(
                f"{LogTag.ONBOARDING} social_profiles done",
                user_id=user_id,
                step="social_profiles",
                outcome="ok",
                emails_in=len(emails),
                raw_count=raw_count,
                deduped_count=len(profiles),
                duration_s=round(time.monotonic() - t0, 2),
            )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} social_profiles failed",
            user_id=user_id,
            step="social_profiles",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(
        user_id,
        OnboardingStage.SOCIAL_PROFILES_READY,
        SocialProfilesReadyPayload(profiles=profiles),
    )
    return profiles


async def _run_holo_card(
    ctx: OnboardingContext,
    user: UserDocument,
    social_profiles: list[SocialProfile],
) -> bool:
    """Generate and persist the holo card. Returns whether it is now viewable —
    the public card page 404s until ``onboarding.house`` exists, so the caller
    must not advertise a link for a card that failed to generate."""
    t0 = time.monotonic()
    card_ready = False
    try:
        context_parts: list[str] = []
        if ctx.triage:
            context_parts.append(f"Inbox summary: {ctx.triage.summary}")
            if ctx.triage.patterns:
                context_parts.append(f"Inbox patterns: {'; '.join(ctx.triage.patterns)}")
            if ctx.triage.important_emails:
                senders = ", ".join(e.sender for e in ctx.triage.important_emails[:5])
                context_parts.append(f"Key contacts: {senders}")
        if ctx.writing_style:
            context_parts.append(f"Writing style: {ctx.writing_style.summary}")
        if social_profiles:
            platforms = ", ".join(f"{p.platform}: {p.url}" for p in social_profiles)
            context_parts.append(f"Social profiles: {platforms}")
        if ctx.focus:
            context_parts.append(f"Current focus: {ctx.focus}")
        for answer in ctx.clarify_answers or []:
            value = (answer.get("value") or "").strip()
            if not value:
                continue
            kind = (answer.get("kind") or "context").strip() or "context"
            context_parts.append(f"{kind.capitalize()}: {value}")
        context_summary = "\n".join(context_parts)

        t_meta = time.monotonic()
        metadata = await get_user_metadata(ctx.user_id, user=user)
        meta_duration_s = round(time.monotonic() - t_meta, 2)
        card_design = generate_profile_card_design()
        t_phrase_bio = time.monotonic()
        phrase, user_bio, bio_status = await generate_holo_card_content(
            ctx.user_id, context_summary, user=user
        )
        phrase_bio_duration_s = round(time.monotonic() - t_phrase_bio, 2)
        t_save = time.monotonic()
        await user_repository.save_personalization(
            ctx.user_id,
            PersonalizationBundle(
                house=card_design.house,
                personality_phrase=phrase,
                user_bio=user_bio,
                bio_status=bio_status,
                account_number=metadata.account_number,
                member_since=metadata.member_since,
                overlay_color=card_design.overlay_color,
                overlay_opacity=card_design.overlay_opacity,
            ),
        )
        card_ready = True
        log.info(
            f"{LogTag.ONBOARDING} holo_card done",
            user_id=ctx.user_id,
            step="holo_card",
            outcome="ok",
            house=card_design.house,
            bio_status=str(bio_status),
            context_chars=len(context_summary),
            meta_duration_s=meta_duration_s,
            phrase_bio_duration_s=phrase_bio_duration_s,
            save_duration_s=round(time.monotonic() - t_save, 2),
            duration_s=round(time.monotonic() - t0, 2),
        )
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} holo_card failed",
            user_id=ctx.user_id,
            step="holo_card",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )

    await _emit_stage(ctx.user_id, OnboardingStage.HOLO_READY)
    return card_ready


def holo_card_url(user_id: str) -> str:
    """The public, shareable holo-card page for a user.

    The route's card id *is* the user id — the card is live as soon as its
    content is saved, so there is nothing to publish first.
    """
    return f"{settings.FRONTEND_URL.rstrip('/')}{_HOLO_CARD_PATH}/{user_id}"


def _holo_card_message(card_url: str) -> str:
    """The seeded chat message announcing the card.

    Chat has no holo-card renderer (no TOOL_RENDERERS entry, no bubble type), so
    the card travels as its public link rather than as a payload the client
    would silently drop.
    """
    return (
        "Your holo card is ready — I built it from what I learned in your inbox.\n\n"
        f"{card_url}\n\n"
        "I also added a lot to your memories while I was in there."
    )


async def _announce_personalization(user_id: str, *, card_ready: bool) -> str | None:
    """Tell the user what the pipeline produced: one notification on every
    channel they have, plus a seeded web conversation holding the card link.

    card_ready is False when holo-card generation failed. The public card
    page 404s until the card exists, so nothing may link to it in that case.
    Returns the seeded conversation id, or None when there is no card to hand
    over or seeding failed. Delivery is fail-soft: an undelivered announcement
    must not fail the pipeline or cost the user their personalization marker.
    """
    card_url = holo_card_url(user_id)
    body = _MEMORIES_NOTIFICATION_BODY
    actions = [
        NotificationAction(
            type=ActionType.REDIRECT,
            label="View memories",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(
                redirect=RedirectConfig(
                    url=MEMORY_SETTINGS_URL,
                    open_in_new_tab=False,
                    close_notification=True,
                )
            ),
        )
    ]
    if card_ready:
        body = f"{body} Your holo card is ready too."
        actions.append(
            NotificationAction(
                type=ActionType.REDIRECT,
                label="See your holo card",
                config=ActionConfig(redirect=RedirectConfig(url=card_url)),
            )
        )

    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.SUCCESS,
                priority=2,
                content=NotificationContent(
                    title=_PERSONALIZATION_NOTIFICATION_TITLE,
                    body=body,
                    actions=actions,
                ),
                metadata={"source": "gmail_personalization"},
            )
        )
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} personalization notification failed",
            user_id=user_id,
            step="announce",
            error=str(e)[:200],
            error_type=type(e).__name__,
        )

    conversation_id = (
        await seed_holo_card_conversation(user_id, _holo_card_message(card_url))
        if card_ready
        else None
    )
    log.info(
        f"{LogTag.ONBOARDING} announce done",
        user_id=user_id,
        step="announce",
        card_ready=card_ready,
        outcome="ok" if conversation_id else "partial",
        conversation_id=conversation_id,
    )
    return conversation_id


async def _persist_social_profiles(user_id: str, social_profiles: list[SocialProfile]) -> None:
    """Write auto-extracted profiles only if the user hasn't already confirmed
    them via POST /social-profiles."""
    if not social_profiles:
        return
    try:
        await user_repository.set_social_profiles_if_unset(user_id, social_profiles)
    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} persist social_profiles failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )


async def _persist_profiles(
    user_id: str,
    writing_style: WritingStyleProfile | None,
    triage: InboxTriage | None,
) -> None:
    """Persist writing style and triage summary. Social profiles are persisted
    separately by _run_social_profiles."""
    t0 = time.monotonic()
    triage_summary: PersistedTriageSummary | None = None
    if triage:
        triage_summary = PersistedTriageSummary(
            total_scanned=triage.total_scanned,
            total_unread=triage.total_unread,
            summary=triage.summary,
            patterns=triage.patterns,
            important_emails=_important_emails_for_client(triage),
        )

    if writing_style or triage:
        try:
            await user_repository.set_writing_style_and_triage(
                user_id,
                writing_style_summary=writing_style.summary if writing_style else None,
                writing_style_example=(writing_style.example if writing_style else None),
                triage_summary=triage_summary,
            )
        except Exception as e:
            log.error(
                f"{LogTag.ONBOARDING} persist update_fields failed",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )

    log.info(
        f"{LogTag.ONBOARDING} persist_profiles done",
        user_id=user_id,
        step="persist_profiles",
        writing_style_persisted=writing_style is not None,
        triage_persisted=triage is not None,
        duration_s=round(time.monotonic() - t0, 2),
    )
