from starlette.requests import HTTPConnection
from workos import AsyncWorkOSClient

from app.config.settings import settings
from app.constants.auth import DEV_USER_HEADER
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser, UserDocument
from shared.py.wide_events import log


async def resolve_dev_bypass_user(connection: HTTPConnection) -> tuple[str, UserDocument | None]:
    """Resolve the dev-bypass target to its Mongo user; the single definition of bypass semantics for both HTTP and WS.

    Precedence: X-Dev-User header (per-request impersonation) > dev_bypass_user cookie (per-browser-profile override) > DEV_AUTH_BYPASS_EMAIL default. Callers own their own failure handling (401 vs WS close).
    """
    target_email: str = (
        connection.headers.get(DEV_USER_HEADER)
        or connection.cookies.get("dev_bypass_user")
        or settings.DEV_AUTH_BYPASS_EMAIL
        or ""
    )
    return target_email, await user_repository.get_by_email(target_email)


def build_user_context(
    user_doc: UserDocument,
    *,
    auth_provider: str | None,
    impersonated: bool = False,
    bot_authenticated: bool = False,
    dev_bypass: bool = False,
) -> AuthenticatedUser:
    """Build the canonical request.state.user from a validated user document; every auth path must go through this one function.

    The whole document is carried so downstream consumers (the agent's dynamic context: timezone, onboarding, custom instructions) always see the same fields — hand-picking a subset previously made voice mode and the bots silently drop the user's system instructions. auth_provider names the path (None for a system-assembled context) and the flags mark it.
    """
    return AuthenticatedUser(
        user_id=user_doc.id,
        auth_provider=auth_provider,
        impersonated=impersonated,
        bot_authenticated=bot_authenticated,
        dev_bypass=dev_bypass,
        email=user_doc.email,
        name=user_doc.name,
        picture=user_doc.picture,
        timezone=user_doc.timezone,
        created_at=user_doc.created_at,
        updated_at=user_doc.updated_at,
        last_active_at=user_doc.last_active_at,
        onboarding=user_doc.onboarding,
        provider_metadata=user_doc.provider_metadata,
        hil_preferences=user_doc.hil_preferences,
        notification_channel_prefs=user_doc.notification_channel_prefs,
        platform_links=user_doc.platform_links,
        platform_links_connected_at=user_doc.platform_links_connected_at,
        chat_channel_priority=user_doc.chat_channel_priority,
        starred_voice_ids=user_doc.starred_voice_ids,
        selected_voice_id=user_doc.selected_voice_id,
        first_name=user_doc.first_name,
        email_memory_processed=user_doc.email_memory_processed,
        email_memory_processed_at=user_doc.email_memory_processed_at,
        email_memory_count=user_doc.email_memory_count,
        integration_scan_states=user_doc.integration_scan_states,
        is_active=user_doc.is_active,
        memory_backfilled=user_doc.memory_backfilled,
        last_inactive_email_sent=user_doc.last_inactive_email_sent,
        inactive_email_count=user_doc.inactive_email_count,
        last_limit_email_sent=user_doc.last_limit_email_sent,
        highest_activity_tier=user_doc.highest_activity_tier,
        highest_activity_tier_at=user_doc.highest_activity_tier_at,
        nurture=user_doc.nurture,
        first_steps=user_doc.first_steps,
        welcome_email_sent_at=user_doc.welcome_email_sent_at,
        marketing_contact_added_at=user_doc.marketing_contact_added_at,
        feature_flags=user_doc.feature_flags,
    )


async def resolve_bot_user(platform: str, platform_user_id: str) -> AuthenticatedUser | None:
    """Resolve a bot-platform account to its user context, or None when unlinked.

    The one way a bot path (middleware or a /bot/* endpoint) turns a platform
    account into the same AuthenticatedUser every other auth path yields.
    """
    user_doc = await user_repository.get_by_platform_id(platform, platform_user_id)
    if user_doc is None:
        return None
    return build_user_context(user_doc, auth_provider=f"bot:{platform}", bot_authenticated=True)


async def load_user_context(user_id: str) -> AuthenticatedUser | None:
    """Build the user context a background path uses to act on user_id's behalf.

    auth_provider is None; the document fields match an interactive turn so the
    agent sees the same timezone and onboarding. None when no such user.
    """
    user_doc = await user_repository.get(user_id)
    if user_doc is None:
        return None
    return build_user_context(user_doc, auth_provider=None)


async def authenticate_workos_session(
    session_token: str, workos_client: AsyncWorkOSClient | None = None
) -> tuple[AuthenticatedUser | None, str | None]:
    """Authenticate a WorkOS session and refresh it if needed; shared between HTTP middleware and WebSocket connections.

    Never raises: returns (None, None) on any failure.
    """
    # Initialize WorkOS client if not provided
    workos = workos_client or AsyncWorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )

    try:
        # Load and authenticate the WorkOS session
        session = await workos.user_management.load_sealed_session(
            sealed_session=session_token,
            cookie_password=settings.WORKOS_COOKIE_PASSWORD,
        )

        auth_response = session.authenticate()
        new_session = None
        workos_user = None

        # Handle authentication result
        if auth_response.authenticated:
            # Authentication successful
            workos_user = auth_response.user
        else:
            # Try to refresh the session
            try:
                refresh_result = await session.refresh(
                    cookie_password=settings.WORKOS_COOKIE_PASSWORD
                )

                if not refresh_result.authenticated:
                    # Authentication failed, even after refresh
                    log.warning(
                        f"{LogTag.AGENT} Authentication failed even after refresh with reason",
                        reason=refresh_result.reason,
                    )
                    return None, None

                workos_user = refresh_result.user
                new_session = refresh_result.sealed_session
                if not workos_user:
                    log.error(
                        f"{LogTag.AGENT} Refresh successful but no user data in refresh result"
                    )
                    return None, new_session

            except Exception as e:
                log.error(
                    f"{LogTag.AGENT} Session refresh error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return None, None

        # Make sure we have a valid user before continuing
        if not workos_user:
            log.error(f"{LogTag.AGENT} Invalid user data from WorkOS")
            return None, new_session

        # Retrieve user from database
        try:
            user_email = workos_user.email
            log.set(auth_provider="workos", user_email=user_email)
            user_doc = await user_repository.get_by_email(user_email)

            if user_doc is None:
                # User doesn't exist in our database
                log.warning(
                    f"{LogTag.AGENT} User authenticated but not found in database",
                    user_email=user_email,
                )
                return None, new_session

            # Prepare user info for return
            user_info = build_user_context(user_doc, auth_provider="workos")
            return user_info, new_session

        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Error processing user data",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None, new_session

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in authenticate_workos_session",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None, None
