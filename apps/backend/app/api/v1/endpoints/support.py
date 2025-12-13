"""Support API router for handling support requests."""

from typing import List, Optional

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

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.api.v1.middleware.rate_limiter import limiter
from app.models.support_models import (
    SupportRequestCreate,
    SupportRequestStatus,
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
from app.services.support_service import (
    create_support_request,
    create_support_request_with_attachments,
    get_user_support_requests,
)

router = APIRouter()


@router.post(
    "/support/requests",
    response_model=SupportRequestSubmissionResponse,
    summary="Submit a support or feature request",
    description="Create a new support request or feature request. Sends email notifications to support team and support to user.",
)
@limiter.limit("5/hour")  # 5 support requests per hour per user
@limiter.limit("10/day")  # 10 support requests per day per user
async def submit_support_request(
    request: Request,
    request_data: SupportRequestCreate,
    current_user: dict = Depends(get_current_user),
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
    try:
        user_id = current_user.get("user_id")
        user_email = current_user.get("email")
        user_name = current_user.get("name")

        if not user_id or not user_email:
            raise HTTPException(status_code=401, detail="User authentication required")

        return await create_support_request(
            request_data=request_data,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to submit support request: {str(e)}"
        )


@router.post(
    "/support/requests/with-attachments",
    response_model=SupportRequestSubmissionResponse,
    summary="Submit a support or feature request with images",
    description="Create a new support request or feature request with image attachments. Sends email notifications to support team and user.",
)
@limiter.limit("5/hour")  # 5 support requests per hour per user
@limiter.limit("10/day")  # 10 support requests per day per user
async def submit_support_request_with_attachments(
    request: Request,
    type: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    attachments: List[UploadFile] = File(default=[]),
    current_user: dict = Depends(get_current_user),
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
        type: Type of request (support or feature)
        title: Title of the request
        description: Description of the request
        attachments: List of uploaded image files (JPG, PNG, WebP only)
        current_user: Current authenticated user

    Returns:
        SupportRequestSubmissionResponse with success status and ticket ID
    """
    try:
        user_id = current_user.get("user_id")
        user_email = current_user.get("email")
        user_name = current_user.get("name")

        if not user_id or not user_email:
            raise HTTPException(status_code=401, detail="User authentication required")

        # Validate request type
        try:
            request_type = SupportRequestType(type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid request type. Must be one of: {', '.join([t.value for t in SupportRequestType])}",
            )

        # Create request data
        request_data = SupportRequestCreate(
            type=request_type,
            title=title,
            description=description,
        )

        return await create_support_request_with_attachments(
            request_data=request_data,
            attachments=attachments,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to submit support request: {str(e)}"
        )


@router.get(
    "/support/requests/my",
    summary="Get user's support requests",
    description="Retrieve all support requests created by the current user with pagination.",
)
@limiter.limit(
    "30/minute"
)  # Rate limit: 30 requests per minute for fetching support requests
async def get_my_support_requests(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page"),
    status: Optional[SupportRequestStatus] = Query(
        None, description="Filter by status"
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Get support requests for the current user.

    Args:
        page: Page number for pagination
        per_page: Number of items per page (max 50)
        status: Optional status filter
        current_user: Current authenticated user

    Returns:
        Dictionary with user's support requests and pagination info
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        return await get_user_support_requests(
            user_id=user_id, page=page, per_page=per_page, status_filter=status
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch support requests: {str(e)}"
        )


@router.get(
    "/support/rate-limit-status",
    summary="Get rate limit status for support requests",
    description="Check current rate limit status for the authenticated user's support requests.",
)
async def get_support_rate_limit_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Get the current rate limit status for support requests.

    Returns information about remaining requests for hourly and daily limits.
    """
    try:
        # This is a simple status endpoint - SlowAPI handles the actual limiting
        # We can return static information about the limits
        return {
            "limits": {
                "hourly": {"limit": 5, "window": "1 hour"},
                "daily": {"limit": 10, "window": "1 day"},
            },
            "note": "Rate limiting is enforced per user. Limits reset at the start of each time window.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get rate limit status: {str(e)}"
        )
