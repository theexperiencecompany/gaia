"""Support API router for handling support requests."""

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_optional_user,
    get_user_id,
)
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.email import GAIA_GITHUB_ISSUES_URL
from app.constants.error_codes import CONTACT_EMAIL_REQUIRED, GAIA_SUPPORT_UNAVAILABLE
from app.constants.general import MAX_PAGE_NUMBER
from app.models.support_models import (
    PublicSupportRequestCreate,
    SupportRateLimits,
    SupportRateLimitStatusResponse,
    SupportRateLimitWindow,
    SupportRequestCreate,
    SupportRequestListResponse,
    SupportRequestSource,
    SupportRequestStatus,
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.support_service import (
    create_support_request,
    create_support_request_with_attachments,
    get_user_support_requests,
)
from app.services.turnstile_service import verify_turnstile_token
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.support import SupportFormSubmitted
from shared.py.wide_events import log


def _require_gaia_support() -> None:
    """Refuse on a self-hosted instance: its users and their data never reach GAIA's support inbox."""
    if not settings.deployment.gaia_support:
        raise AppError(
            message="In-app support is not available on a self-hosted instance",
            fix=f"Report bugs and request features on GitHub: {GAIA_GITHUB_ISSUES_URL}",
            status_code=404,
            code=GAIA_SUPPORT_UNAVAILABLE,
        )


router = APIRouter(dependencies=[Depends(_require_gaia_support)])


@router.post(
    "/support/requests",
    response_model=SupportRequestSubmissionResponse,
    summary="Submit a support or feature request",
    description="Create a new support request or feature request. Sends email notifications to support team and support to user.",
)
@limiter.limit("5/hour")  # 5 support requests per hour per user
@limiter.limit("10/day")  # 10 support requests per day per user
async def submit_support_request(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires this param in the signature
    request_data: SupportRequestCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> SupportRequestSubmissionResponse:
    """
    Submit a new support or feature request.

    This endpoint:
    - Creates a support request in the database
    - Generates a unique ticket ID
    - Sends email notification to support team
    - Sends confirmation email to the user

    Args:
        request_data: Support request details
        current_user: Current authenticated user

    Returns:
        SupportRequestSubmissionResponse with success status and ticket ID
    """
    log.set(operation="submit_support_request", category=request_data.type)
    try:
        user_id = current_user.user_id
        user_email = current_user.email
        user_name = current_user.name

        if not user_id or not user_email:
            raise HTTPException(status_code=401, detail="User authentication required")

        result = await create_support_request(
            request_data=request_data,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )
        log.set(ticket_id=result.ticket_id)
        log.set(outcome="success")
        capture(
            UserId(user_id),
            SupportFormSubmitted(
                request_type=request_data.type.value,
                title_length=len(request_data.title),
                description_length=len(request_data.description),
                attachment_count=0,
            ),
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to submit support request: {e!s}"
        ) from e


@router.post(
    "/support/requests/with-attachments",
    response_model=SupportRequestSubmissionResponse,
    summary="Submit a support or feature request with images",
    description="Create a new support request or feature request with image attachments. Sends email notifications to support team and user.",
)
@limiter.limit("5/hour")  # 5 support requests per hour per user
@limiter.limit("10/day")  # 10 support requests per day per user
async def submit_support_request_with_attachments(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires this param in the signature
    # Renamed from the wire field `type` to avoid shadowing the builtin;
    # `alias="type"` keeps the multipart field name the frontend sends
    # (apps/web/src/features/support/api/supportApi.ts) unchanged.
    ticket_type: str = Form(..., alias="type"),
    title: str = Form(...),
    description: str = Form(...),
    attachments: list[UploadFile] = File(default=[]),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> SupportRequestSubmissionResponse:
    """
    Submit a new support or feature request with image attachments.

    This endpoint:
    - Creates a support request in the database
    - Uploads image attachments to storage
    - Generates a unique ticket ID
    - Sends email notification to support team with images
    - Sends confirmation email to the user

    Args:
        ticket_type: Type of request (support or feature)
        title: Title of the request
        description: Description of the request
        attachments: List of uploaded image files (JPG, PNG, WebP only)
        current_user: Current authenticated user

    Returns:
        SupportRequestSubmissionResponse with success status and ticket ID
    """
    log.set(operation="submit_support_request_with_attachments", category=ticket_type)
    try:
        user_id = current_user.user_id
        user_email = current_user.email
        user_name = current_user.name

        if not user_id or not user_email:
            raise HTTPException(status_code=401, detail="User authentication required")

        # Validate request type
        try:
            request_type = SupportRequestType(ticket_type)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid request type. Must be one of: {', '.join([t.value for t in SupportRequestType])}",
            ) from e

        # Create request data
        request_data = SupportRequestCreate(
            type=request_type,
            title=title,
            description=description,
        )

        result = await create_support_request_with_attachments(
            request_data=request_data,
            attachments=attachments,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )
        log.set(ticket_id=result.ticket_id)
        log.set(outcome="success")
        capture(
            UserId(user_id),
            SupportFormSubmitted(
                request_type=request_data.type.value,
                title_length=len(request_data.title),
                description_length=len(request_data.description),
                attachment_count=len(attachments),
            ),
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to submit support request: {e!s}"
        ) from e


@router.post(
    "/support/requests/public",
    summary="Submit a contact request without signing in",
    description="Create a support or feature request from the public contact form. Verifies a Cloudflare Turnstile token and is rate-limited per client IP.",
)
@limiter.limit("5/hour")  # per client IP: the limiter keys on the remote address
@limiter.limit("10/day")
async def submit_public_support_request(
    request: Request,
    request_data: PublicSupportRequestCreate,
    current_user: AuthenticatedUser | None = Depends(get_optional_user),
) -> SupportRequestSubmissionResponse:
    """Submit a contact-form request for a visitor, or for a signed-in caller who has no email on file."""
    log.set(
        operation="submit_public_support_request",
        category=request_data.type,
        signed_in=current_user is not None,
    )
    user_id = current_user.user_id if current_user and current_user.user_id else None
    user_email = (current_user.email if current_user else None) or request_data.email
    if not user_email:
        raise AppError(
            message="An email address is required so we can reply",
            fix="Add your email address to the form",
            status_code=422,
            code=CONTACT_EMAIL_REQUIRED,
        )

    await verify_turnstile_token(
        request_data.turnstile_token, request.client.host if request.client else None
    )
    result = await create_support_request(
        request_data=SupportRequestCreate(
            type=request_data.type,
            title=request_data.title,
            description=request_data.description,
        ),
        user_id=user_id,
        user_email=user_email,
        user_name=request_data.name or (current_user.name if current_user else None),
        source=SupportRequestSource.PUBLIC_CONTACT_FORM,
    )
    log.set(ticket_id=result.ticket_id, outcome="success")
    # A visitor has no analytics identity: distinct_id is only ever a GAIA user id.
    if user_id:
        capture(
            UserId(user_id),
            SupportFormSubmitted(
                request_type=request_data.type.value,
                title_length=len(request_data.title),
                description_length=len(request_data.description),
                attachment_count=0,
            ),
        )
    return result


@router.get(
    "/support/requests/my",
    summary="Get user's support requests",
    description="Retrieve all support requests created by the current user with pagination.",
)
@limiter.limit("30/minute")  # Rate limit: 30 requests per minute for fetching support requests
async def get_my_support_requests(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires this param in the signature
    page: int = Query(1, ge=1, le=MAX_PAGE_NUMBER, description="Page number"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page"),
    status: SupportRequestStatus | None = Query(None, description="Filter by status"),
    user_id: str = Depends(get_user_id),
) -> SupportRequestListResponse:
    """Get the current user's support requests, newest first, paginated."""
    log.set(operation="list_support_requests")
    try:
        result = await get_user_support_requests(
            user_id=user_id, page=page, per_page=per_page, status_filter=status
        )
        log.set(outcome="success")
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch support requests: {e!s}"
        ) from e


@router.get(
    "/support/rate-limit-status",
    summary="Get rate limit status for support requests",
    description="Check current rate limit status for the authenticated user's support requests.",
)
async def get_support_rate_limit_status(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires this param in the signature
    current_user: AuthenticatedUser = Depends(get_current_user),  # noqa: ARG001 -- injected for auth side-effect only
) -> SupportRateLimitStatusResponse:
    """
    Get the current rate limit status for support requests.

    Returns information about remaining requests for hourly and daily limits.
    """
    log.set(operation="get_support_rate_limit_status")
    try:
        # This is a simple status endpoint - SlowAPI handles the actual limiting
        # We can return static information about the limits
        result = SupportRateLimitStatusResponse(
            limits=SupportRateLimits(
                hourly=SupportRateLimitWindow(limit=5, window="1 hour"),
                daily=SupportRateLimitWindow(limit=10, window="1 day"),
            ),
            note="Rate limiting is enforced per user. Limits reset at the start of each time window.",
        )
        log.set(outcome="success")
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get rate limit status: {e!s}"
        ) from e
