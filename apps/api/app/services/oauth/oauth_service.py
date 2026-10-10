import asyncio
from datetime import UTC, datetime

from fastapi import BackgroundTasks, HTTPException
from workos.types.user_management.authentication_response import AuthenticationMethod

from app.constants.email import SIGNUP_EMAIL_ENQUEUE_TIMEOUT_SECONDS
from app.constants.integrations import (
    GMAIL_INTEGRATION_ID,
    GOOGLE_CALENDAR_INTEGRATION_ID,
)
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.users import user_repository
from app.models.oauth_models import OAuthIntegration
from app.models.user_models import BioStatus, UserDocument, UserUpdate
from app.services.analytics_service import track_login, track_signup
from app.services.composio.composio_service import get_composio_service
from app.services.email.signup_delivery import enqueue_signup_emails
from app.services.integrations.integration_account_lifecycle import (
    AccountConnected,
    AccountLimitReached,
    record_connected_account,
    resync_primary_bound_triggers,
)

# Re-exported on purpose: the reader lives below this module now, and its
# callers here keep importing it from the OAuth surface they already know.
from app.services.integrations.integration_status import (
    get_all_integrations_status as get_all_integrations_status,  # noqa: PLC0414 -- re-export
)
from app.services.integrations.user_integration_status import publish_connected
from app.services.onboarding.intelligence_job import enqueue_gmail_personalization
from app.services.system_workflows.provisioner import provision_system_workflows
from app.services.todos.inbox_desk import queue_inbox_desk_provision
from app.services.workflow.dormancy import resume_dormancy_paused_workflows
from app.services.workflow.integration_pause import (
    resume_workflows_for_reconnected_integration,
)
from app.services.workspace_sync import schedule_user_provision
from app.utils.email_utils import derive_name_from_email
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.wide_events import log, spawn_logged_task


def _returning_user_profile(
    existing_user: UserDocument, name: str, picture_url: str | None
) -> tuple[dict[str, str], str]:
    """Profile fields to write on a login, plus the name analytics should report."""
    update_fields: dict[str, str] = {}

    # The stored name wins on every login. WorkOS re-sends its own guess each
    # time, and unconditionally writing it clobbered whatever the user had
    # corrected in settings. Only fill a name that isn't there yet.
    stored_name = (existing_user.name or "").strip()
    if name and not stored_name:
        update_fields["name"] = name
        stored_name = name

    # Update picture URL if provided, otherwise keep existing or set empty
    if picture_url:
        update_fields["picture"] = picture_url
    elif not existing_user.picture:
        update_fields["picture"] = ""

    return update_fields, stored_name


async def _run_signup_side_effects(
    user_id: str, email: str, signup_name: str, auth_method: AuthenticationMethod | None
) -> None:
    """Outbound effects of a signup — none of them may fail the signup itself."""
    # Track signup with the stable Mongo user id as the PostHog distinct id.
    try:
        track_signup(
            user_id=UserId(user_id),
            email=email,
            name=signup_name,
            signup_method=auth_method,
        )
        log.info(f"{LogTag.OAUTH} Signup tracked in PostHog for new user", user={"id": user_id})
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to track signup in PostHog for",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )

    # Welcome email + marketing contact must not block signup (observed 90s+ hangs): queued so
    # a restart doesn't drop them, bounded so a stalled Redis can't hold the OAuth callback. A
    # lost enqueue is survivable via the hourly recovery sweep.
    try:
        async with asyncio.timeout(SIGNUP_EMAIL_ENQUEUE_TIMEOUT_SECONDS):
            pool = await RedisPoolManager.get_pool()
            await enqueue_signup_emails(pool, user_id)
        log.info(f"{LogTag.OAUTH} Queued signup email delivery", user={"id": user_id})
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to queue signup email delivery",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )

    # Provision the user's workspace (system files + skills catalog) now, instead
    # of lazily on the first chat turn. Fire-and-forget so signup isn't blocked.
    schedule_user_provision(user_id)


async def store_user_info(
    name: str,
    email: str,
    picture_url: str | None,
    *,
    auth_method: AuthenticationMethod | None,
    external_side_effects: bool = True,
) -> tuple[str, bool]:
    """Store user info from a Google callback, updating or creating the user.

    external_side_effects=False skips signup emails/analytics/workspace
    provisioning while keeping the stored data shape identical, for dev/test minting.
    """
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Check if user already exists
    existing_user = await user_repository.get_by_email(email)

    if existing_user:
        update_fields, stored_name = _returning_user_profile(existing_user, name, picture_url)

        if update_fields:
            await user_repository.update(existing_user.id, UserUpdate(**update_fields))
        if external_side_effects:
            # Only workflows the dormancy sweep paused resume — never one the
            # user switched off themselves (that records no reason).
            # Fire-and-forget so re-registering triggers can't slow or fail a login.
            spawn_logged_task(
                "resume_dormancy_paused_workflows",
                resume_dormancy_paused_workflows(existing_user.id),
            )
            try:
                track_login(
                    user_id=UserId(existing_user.id),
                    email=email,
                    name=stored_name,
                    login_method=auth_method,
                )
            except Exception as e:
                log.error(
                    f"{LogTag.OAUTH} Failed to track login in PostHog for",
                    user={"id": existing_user.id},
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return existing_user.id, False

    # WorkOS often has no first/last name (email-code signups), which used to
    # store an empty name forever. The email's local part is the fallback; the
    # user can correct it in settings and no later login overwrites it.
    signup_name = name or derive_name_from_email(email)
    # Suppressed side effects mean this user owes no signup delivery, so stamps
    # are set on insert (the recovery sweep selects on a *missing* stamp and
    # would otherwise mail/enrol every seeded account an hour later).
    settled_at = None if external_side_effects else datetime.now(UTC)
    created = await user_repository.create(
        UserDocument(
            name=signup_name,
            email=email,
            picture=picture_url or "",
            welcome_email_sent_at=settled_at,
            marketing_contact_added_at=settled_at,
        )
    )

    if not external_side_effects:
        return created.id, True

    await _run_signup_side_effects(created.id, email, signup_name, auth_method)

    return created.id, True


async def check_integration_status(integration_id: str, user_id: str) -> bool:
    """Return True if integration_id is connected for user_id.

    Uses the cached get_all_integrations_status(), so it hits the cache once per user.
    """
    try:
        all_statuses: dict[str, bool] = await get_all_integrations_status(user_id)
        return all_statuses.get(integration_id, False)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Error checking integration status for",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return False


async def check_multiple_integrations_status(
    integration_ids: list[str], user_id: str
) -> dict[str, bool]:
    """Return connection status for each of integration_ids, from the cached status map."""
    try:
        all_statuses = await get_all_integrations_status(user_id)
        return {
            integration_id: all_statuses.get(integration_id, False)
            for integration_id in integration_ids
        }
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Error checking multiple integrations status",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return dict.fromkeys(integration_ids, False)


def _setup_account_triggers(
    user_id: str,
    integration_config: OAuthIntegration,
    connected: AccountConnected,
    background_tasks: BackgroundTasks,
) -> None:
    """Subscribe the new account to account-level events; move workflow triggers if the primary moved."""
    log.info(
        f"{LogTag.OAUTH} Setting up triggers for connected account",
        associated_triggers_count=len(integration_config.associated_triggers),
        user_id=user_id,
        id=integration_config.id,
    )
    background_tasks.add_task(
        get_composio_service().handle_subscribe_trigger,
        user_id=user_id,
        connected_account_id=connected.account.connected_account_id,
        triggers=integration_config.associated_triggers,
    )
    # Workflow and todo triggers live on the primary account only, so they are
    # re-registered when a connect replaced it or made a first one.
    if connected.primary_changed:
        background_tasks.add_task(resync_primary_bound_triggers, user_id, integration_config)


async def _refresh_bio_status_for_reconnect(user_id: str, user_doc: UserDocument) -> None:
    """Bump a bio generated without Gmail back to processing so the UI re-runs."""
    try:
        current_bio_status = user_doc.onboarding.bio_status if user_doc.onboarding else None
        if current_bio_status == BioStatus.NO_GMAIL:
            await user_repository.set_bio_status(user_id, BioStatus.PROCESSING)
            log.info(
                f"{LogTag.OAUTH} Updated bio_status to processing",
                user_id=user_id,
                current_bio_status=current_bio_status,
            )
            try:
                if isinstance(user_id, str) and user_id:
                    await websocket_manager.broadcast_to_user(
                        user_id=user_id,
                        message={
                            "type": "bio_status_update",
                            "data": {"bio_status": BioStatus.PROCESSING},
                        },
                    )
            except Exception as ws_error:
                log.warning(
                    f"{LogTag.OAUTH} Failed to send WebSocket update",
                    error=str(ws_error),
                    error_type=type(ws_error).__name__,
                    user_id=user_id,
                )
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Error updating bio_status for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )


async def _handle_gmail_connection(user_id: str) -> None:
    """Kick off the personalization pipeline (or plain ingestion) for a Gmail connect."""
    log.info(f"{LogTag.OAUTH} Starting Gmail email processing for user", user_id=user_id)

    user_doc = None
    try:
        user_doc = await user_repository.get(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to load user_doc for",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )

    onboarding = user_doc.onboarding if user_doc is not None else None
    onboarding_completed = bool(onboarding and onboarding.completed)

    # If bio was generated without Gmail (post-onboarding reconnect),
    # bump bio_status back to processing so the UI re-runs.
    if onboarding_completed and user_doc is not None:
        await _refresh_bio_status_for_reconnect(user_id, user_doc)

    # Connecting Gmail is what earns the personalization pipeline: inbox scan,
    # memory ingestion, writing style, triage, social profiles, holo card. It
    # runs once per user, so a reconnect after an unlink does not redo it.
    personalization_job_id = await enqueue_gmail_personalization(user_id)
    if personalization_job_id is None:
        # No pipeline this time, so nothing else will queue ingestion. Queue it
        # directly; when the pipeline does run it queues ingestion itself, after
        # its scan, so the two never contend for Composio Gmail capacity.
        try:
            pool = await RedisPoolManager.get_pool()
            await enqueue_worker_job(pool, "process_gmail_emails_to_memory", user_id)
            log.info(f"{LogTag.OAUTH} Queued Gmail processing job for user", user_id=user_id)
        except Exception as e:
            log.error(
                f"{LogTag.OAUTH} Failed to queue Gmail processing",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                exc_info=True,
            )


async def handle_oauth_connection(
    user_id: str,
    integration_config: OAuthIntegration,
    background_tasks: BackgroundTasks,
    connected_account_id: str,
) -> AccountConnected | AccountLimitReached:
    """Record the account that just authorized, then run its connect side effects."""
    log.set(auth={"user_id": user_id, "provider": integration_config.id})
    log.set_ns(
        "oauth",
        operation="connect",
        provider=integration_config.provider,
        integration_id=integration_config.id,
    )

    connected = await record_connected_account(user_id, integration_config, connected_account_id)
    if isinstance(connected, AccountLimitReached):
        return connected
    log.info(f"{LogTag.OAUTH} Recorded connected account for", id=integration_config.id)
    await publish_connected(user_id, integration_config.id)

    if integration_config.associated_triggers:
        _setup_account_triggers(user_id, integration_config, connected, background_tasks)

    # Personalization reads the primary inbox; a further account adds no profile.
    if integration_config.id == GMAIL_INTEGRATION_ID and connected.primary_changed:
        await _handle_gmail_connection(user_id)

    if connected.primary_changed:
        # Workflows bind to the primary, so only its return can unblock them.
        background_tasks.add_task(
            resume_workflows_for_reconnected_integration,
            user_id,
            integration_config.id,
        )
        if integration_config.id == GMAIL_INTEGRATION_ID:
            background_tasks.add_task(queue_inbox_desk_provision, user_id)
            log.info(f"{LogTag.OAUTH} Queued Inbox desk provisioning", user_id=user_id)
        if integration_config.id == GOOGLE_CALENDAR_INTEGRATION_ID:
            background_tasks.add_task(
                provision_system_workflows,
                user_id=user_id,
                integration_id=integration_config.id,
                integration_display_name=integration_config.name,
            )
            log.info(
                f"{LogTag.OAUTH} Queued system workflow provisioning",
                user_id=user_id,
                id=integration_config.id,
            )
    return connected
