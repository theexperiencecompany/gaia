from fastapi import BackgroundTasks, HTTPException

from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_scopes,
)
from app.config.token_repository import token_repository
from app.constants.auth import LOGIN_METHOD_WORKOS
from app.constants.cache import OAUTH_STATUS_KEY
from app.constants.integrations import (
    GMAIL_INTEGRATION_ID,
    GOOGLE_CALENDAR_INTEGRATION_ID,
    INTEGRATION_STATUS_CONNECTED,
    MANAGED_BY_COMPOSIO,
    MANAGED_BY_MCP,
    MANAGED_BY_SELF,
)
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.users import user_repository
from app.decorators.caching import Cacheable
from app.models.oauth_models import OAuthIntegration
from app.models.user_models import BioStatus, UserDocument, UserUpdate
from app.services.analytics_service import track_login, track_signup
from app.services.composio.composio_service import get_composio_service
from app.services.email import add_marketing_contact, send_welcome_email
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.provider_metadata_service import (
    fetch_and_store_provider_metadata,
)
from app.services.system_workflows.provisioner import provision_system_workflows
from app.services.workflow.dormancy import resume_dormancy_paused_workflows
from app.services.workflow.integration_pause import (
    resume_workflows_for_reconnected_integration,
)
from app.services.workflow.trigger_service import TriggerService
from app.services.workspace_sync import schedule_user_provision
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import OAuthContext, log, spawn_logged_task


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
        update_fields: dict[str, str] = {"name": name}

        # Update picture URL if provided, otherwise keep existing or set empty
        if picture_url:
            update_fields["picture"] = picture_url
        elif not existing_user.picture:
            update_fields["picture"] = ""

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
                    name=name,
                    login_method=LOGIN_METHOD_WORKOS,
                )
            except Exception as e:
                log.error(
                    f"{LogTag.OAUTH} Failed to track login in PostHog for",
                    email=email,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return existing_user.id, False

    created = await user_repository.create(
        UserDocument(name=name, email=email, picture=picture_url or "")
    )

    if not external_side_effects:
        return created.id, True

    # Track signup with the stable Mongo user id as the PostHog distinct id.
    try:
        track_signup(
            user_id=created.id,
            email=email,
            name=name,
            signup_method=LOGIN_METHOD_WORKOS,
        )
        log.info(f"{LogTag.OAUTH} Signup tracked in PostHog for new user", email=email)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to track signup in PostHog for",
            email=email,
            error=str(e),
            error_type=type(e).__name__,
        )

    # Send welcome email to new user
    try:
        await send_welcome_email(email, name)
        log.info(f"{LogTag.OAUTH} Welcome email sent to new user", email=email)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to send welcome email to",
            email=email,
            error=str(e),
            error_type=type(e).__name__,
        )
        # Don't raise exception - user creation should still succeed

    # Add contact to marketing audience
    try:
        await add_marketing_contact(email, name)
        log.info(f"{LogTag.OAUTH} Contact added to marketing audience for new user", email=email)
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to add marketing contact for",
            email=email,
            error=str(e),
            error_type=type(e).__name__,
        )
        # Don't raise exception - user creation should still succeed

    # Provision the user's workspace (system files + skills catalog) now, instead
    # of lazily on the first chat turn. Fire-and-forget so signup isn't blocked.
    schedule_user_provision(created.id)

    return created.id, True


@Cacheable(ttl=86400, key_pattern=f"{OAUTH_STATUS_KEY}:{{user_id}}")
async def get_all_integrations_status(user_id: str) -> dict[str, bool]:
    """
    Get status for ALL integrations for a user. This is the ONLY cached function.

    Strategy:
    1. Query MongoDB user_integrations first (canonical source for user connections)
    2. For platform integrations not in user_integrations, check external services
       (supports legacy users who connected before user_integrations existed)

    Args:
        user_id: The user ID to check status for

    Returns:
        dict[str, bool]: Mapping of integration_id -> connection status for ALL integrations
    """
    result = {}

    # Step 1: Get all user_integrations from MongoDB (canonical source)
    user_ints = await user_integration_repository.list_for_user(user_id, limit=100)
    mongo_status = {
        ui.integration_id: ui.status == INTEGRATION_STATUS_CONNECTED for ui in user_ints
    }

    # Track which platform integrations need external verification
    composio_providers = []
    composio_id_to_provider = {}

    for integration in OAUTH_INTEGRATIONS:
        if not integration.available:
            result[integration.id] = False
            continue

        # If user has this integration in MongoDB, use that status
        if integration.id in mongo_status:
            result[integration.id] = mongo_status[integration.id]
            continue

        # Not in MongoDB - check external services (legacy support)
        if integration.managed_by == MANAGED_BY_MCP:
            # All MCPs (auth or not) use MongoDB user_integrations as source of truth
            # If not in mongo_status, they're not connected
            result[integration.id] = False
        elif integration.managed_by == MANAGED_BY_COMPOSIO:
            composio_providers.append(integration.provider)
            composio_id_to_provider[integration.id] = integration.provider
        elif integration.managed_by == MANAGED_BY_SELF:
            # Check self-managed integrations (Google) via PostgreSQL tokens
            try:
                token = await token_repository.get_token(
                    user_id, integration.provider, renew_if_expired=True
                )
                authorized_scopes = str(token.get("scope", "")).split()
                required_scopes = get_integration_scopes(integration.id)
                result[integration.id] = all(
                    scope in authorized_scopes for scope in required_scopes
                )
            except Exception as e:
                log.debug(
                    f"{LogTag.OAUTH} Token not found for",
                    provider=integration.provider,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                result[integration.id] = False

    # Step 2: Batch check Composio integrations not in MongoDB
    if composio_providers:
        try:
            composio_service = get_composio_service()
            status_map = await composio_service.check_connection_status(composio_providers, user_id)
            for integration_id, provider in composio_id_to_provider.items():
                result[integration_id] = status_map.get(provider, False)
        except Exception as e:
            log.error(
                f"{LogTag.OAUTH} Error batch checking Composio integrations",
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            for integration_id in composio_id_to_provider:
                result[integration_id] = False

    # Include custom integrations from MongoDB that are connected
    for integration_id, is_connected in mongo_status.items():
        if integration_id not in result:
            result[integration_id] = is_connected

    log.set(oauth=OAuthContext(operation="status"), result_count=len(result))
    return result


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

    # Process Gmail emails to memory if this is a Gmail connection
    if integration_config.id == GMAIL_INTEGRATION_ID:
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

        onboarding = (user_doc.onboarding if user_doc else None) or {}
        onboarding_completed = bool(onboarding.get("completed"))

        # If bio was generated without Gmail (post-onboarding reconnect),
        # bump bio_status back to processing so the UI re-runs.
        if onboarding_completed and user_doc:
            try:
                current_bio_status = onboarding.get("bio_status")
                if current_bio_status in [BioStatus.NO_GMAIL, "no_gmail"]:
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

        # During onboarding the pipeline enqueues this job itself; queuing here
        # too would contend for Composio Gmail capacity with the visible scan.
        if onboarding_completed:
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
        else:
            log.info(
                f"{LogTag.OAUTH} Deferring Gmail->memory ingestion until onboarding pipeline completes for user",
                user_id=user_id,
            )

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
