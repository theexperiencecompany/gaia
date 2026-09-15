from fastapi import BackgroundTasks, HTTPException

from app.constants.auth import LOGIN_METHOD_WORKOS
from app.constants.integrations import (
    GMAIL_INTEGRATION_ID,
    GOOGLE_CALENDAR_INTEGRATION_ID,
    INTEGRATION_STATUS_CONNECTED,
)
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.users import user_repository
from app.models.oauth_models import OAuthIntegration
from app.models.user_models import BioStatus, UserDocument, UserUpdate
from app.services.analytics_service import track_login, track_signup
from app.services.composio.composio_service import get_composio_service
from app.services.email import add_marketing_contact, send_welcome_email

# Re-exported on purpose: the reader lives below this module now, and its
# callers here keep importing it from the OAuth surface they already know.
from app.services.integrations.integration_status import (
    get_all_integrations_status as get_all_integrations_status,  # noqa: PLC0414 -- re-export
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.onboarding.intelligence_job import enqueue_gmail_personalization
from app.services.provider_metadata_service import (
    fetch_and_store_provider_metadata,
)
from app.services.system_workflows.provisioner import provision_system_workflows
from app.services.triggers.subscription_service import resync_subscriptions_for_trigger_names
from app.services.workflow.dormancy import resume_dormancy_paused_workflows
from app.services.workflow.integration_pause import (
    resume_workflows_for_reconnected_integration,
)
from app.services.workflow.trigger_service import TriggerService
from app.services.workspace_sync import schedule_user_provision
from app.utils.email_utils import derive_name_from_email
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
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


async def _run_signup_side_effects(user_id: str, email: str, signup_name: str) -> None:
    """Outbound effects of a signup — none of them may fail the signup itself."""
    # Track signup with the stable Mongo user id as the PostHog distinct id.
    try:
        track_signup(
            user_id=user_id,
            email=email,
            name=signup_name,
            signup_method=LOGIN_METHOD_WORKOS,
        )
        log.info(f"{LogTag.OAUTH} Signup tracked in PostHog for new user", user={"id": user_id})
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to track signup in PostHog for",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )

    # Send welcome email to new user
    try:
        await send_welcome_email(email, signup_name, user_id=user_id)
        log.info(f"{LogTag.OAUTH} Welcome email sent to new user", user={"id": user_id})
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to send welcome email to",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )

    # Add contact to marketing audience
    try:
        await add_marketing_contact(email, signup_name, user_id=user_id)
        log.info(
            f"{LogTag.OAUTH} Contact added to marketing audience for new user",
            user={"id": user_id},
        )
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to add marketing contact for",
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
    external_side_effects: bool = True,
) -> tuple[str, bool]:
    """
    Stores user info from Google callback.

    - Updates existing users or creates new ones
    - Stores profile picture URL directly without processing

    Args:
        name (str): The user's name.
        email (str): The user's email.
        picture_url (str): The URL of the profile picture from Google.
        external_side_effects: When False, skip the outbound effects of signup
            (PostHog events, welcome email, marketing audience, workspace
            provisioning) while keeping the stored data shape identical — for
            dev/test minting, which must never email or pollute analytics.

    Returns:
        tuple[str, bool]: (user_id, is_new_user)

    Raises:
        HTTPException: If any step in the process fails.
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
            # A returning user gets back only the workflows the dormancy sweep
            # paused — never one they switched off themselves (that records no
            # reason). Fire-and-forget: re-registering triggers must not slow or
            # fail a login.
            spawn_logged_task(
                "resume_dormancy_paused_workflows",
                resume_dormancy_paused_workflows(existing_user.id),
            )
            try:
                track_login(
                    user_id=existing_user.id,
                    email=email,
                    name=stored_name,
                    login_method=LOGIN_METHOD_WORKOS,
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
    created = await user_repository.create(
        UserDocument(name=signup_name, email=email, picture=picture_url or "")
    )

    if not external_side_effects:
        return created.id, True

    await _run_signup_side_effects(created.id, email, signup_name)

    return created.id, True


async def check_integration_status(integration_id: str, user_id: str) -> bool:
    """
    Check if a specific integration is connected.

    This function uses the cached get_all_integrations_status() to avoid making
    unnecessary API calls. It will only hit the cache once per user.

    Args:
        integration_id: The integration ID to check (e.g., 'gmail', 'calendar', 'notion')
        user_id: The user ID to check status for

    Returns:
        bool: True if the integration is connected, False otherwise
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
    """
    Check status for multiple integrations.

    This function uses the cached get_all_integrations_status() to efficiently
    return status for multiple integrations without making additional API calls.

    Args:
        integration_ids: List of integration IDs to check
        user_id: The user ID to check status for

    Returns:
        dict[str, bool]: Mapping of integration_id -> connection status
    """
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


def _setup_integration_triggers(
    user_id: str, integration_config: OAuthIntegration, background_tasks: BackgroundTasks
) -> None:
    composio_service = get_composio_service()
    log.info(
        f"{LogTag.OAUTH} Setting up triggers for user and integration",
        associated_triggers_count=len(integration_config.associated_triggers),
        user_id=user_id,
        id=integration_config.id,
    )
    background_tasks.add_task(
        composio_service.handle_subscribe_trigger,
        user_id=user_id,
        triggers=integration_config.associated_triggers,
    )

    # A (re)connect creates a fresh Composio connected account, which strands
    # any per-workflow triggers registered against the old one. Re-register
    # this integration's workflow triggers so existing workflows keep firing.
    workflow_trigger_names = [
        t.workflow_trigger_schema.slug
        for t in integration_config.associated_triggers
        if t.workflow_trigger_schema
    ]
    if workflow_trigger_names:
        background_tasks.add_task(
            TriggerService.resync_user_workflow_triggers,
            user_id,
            workflow_trigger_names,
        )
        # Todo subscriptions register against the same connected account, so a
        # reconnect strands their trigger ids exactly as it strands workflows'.
        background_tasks.add_task(
            resync_subscriptions_for_trigger_names,
            user_id,
            set(workflow_trigger_names),
        )


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
    connected_account_id: str | None = None,
) -> None:
    """
    Handle successful OAuth connection: setup triggers, update bio status, queue processing.

    Args:
        user_id: The user ID
        integration_config: The integration configuration object
        background_tasks: FastAPI background tasks
        connected_account_id: Composio's nanoid for the account that just authorized
    """
    log.set(auth={"user_id": user_id, "provider": integration_config.id})
    log.set_ns(
        "oauth",
        operation="connect",
        provider=integration_config.provider,
        integration_id=integration_config.id,
    )

    # Setup triggers if available
    if integration_config.associated_triggers:
        _setup_integration_triggers(user_id, integration_config, background_tasks)

    # Process Gmail emails to memory if this is a Gmail connection
    if integration_config.id == GMAIL_INTEGRATION_ID:
        await _handle_gmail_connection(user_id)

    # Update user_integrations status in MongoDB. The @CacheInvalidator on
    # update_user_integration_status busts the full USER_INTEGRATION_CACHE_PATTERNS
    # set (OAUTH_STATUS + tools:user:* + tool_namespaces), so no manual delete here.
    try:
        await update_user_integration_status(
            user_id,
            integration_config.id,
            INTEGRATION_STATUS_CONNECTED,
            connected_account_id=connected_account_id,
        )
        log.info(f"{LogTag.OAUTH} Updated user_integrations status for", id=integration_config.id)
        # Runs after the status write above, and as a background task, so the
        # reconnected integration already reads as connected by the time
        # activate_workflow re-checks the workflow's requirements.
        background_tasks.add_task(
            resume_workflows_for_reconnected_integration,
            user_id,
            integration_config.id,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.OAUTH} Failed to update user_integrations status",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

    if integration_config.metadata_config:
        background_tasks.add_task(
            fetch_and_store_provider_metadata,
            user_id=user_id,
            integration_id=integration_config.id,
        )
        log.info(
            f"{LogTag.OAUTH} Queued metadata fetch for user and integration",
            user_id=user_id,
            id=integration_config.id,
        )

    # Auto-provision system workflows for supported integrations
    if integration_config.id in (GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID):
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
