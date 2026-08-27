"""
FastAPI endpoints for reminder management.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.constants.log_tags import LogTag
from app.decorators import tiered_rate_limit
from app.models.reminder_models import (
    CreateReminderRequest,
    CronValidationResponse,
    ReminderModel,
    ReminderResponse,
    ReminderStatus,
    ReminderUpdate,
    UpdateReminderRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.reminder_service import reminder_scheduler
from app.utils.cron_utils import (
    calculate_next_occurrences,
    get_next_run_time,
    validate_cron_expression,
)
from shared.py.wide_events import ReminderContext, log

_CRON_PREVIEW_RUNS = 5

router = APIRouter(prefix="/reminders", tags=["reminders"])


def _reminder_context(operation: str, reminder: ReminderModel) -> ReminderContext:
    """Wide-event context for one reminder.

    ``recurrence`` and ``next_run_time`` read ``repeat``/``scheduled_at`` — the
    fields a reminder actually has. The previous
    ``reminder.recurrence if hasattr(reminder, "recurrence") else None`` spelling
    named attributes ``ReminderModel`` has never defined, so both fields were
    logged as ``None`` on every request.
    """
    context = ReminderContext(operation=operation, id=str(reminder.id))
    if reminder.repeat:
        context["recurrence"] = reminder.repeat
    if reminder.scheduled_at:
        context["next_run_time"] = reminder.scheduled_at.isoformat()
    return context


@router.post("", response_model=ReminderResponse, status_code=http_status.HTTP_201_CREATED)
@tiered_rate_limit("reminder_operations")
async def create_reminder_endpoint(
    reminder_data: CreateReminderRequest,
    user_timezone: Annotated[str, Depends(get_user_timezone_from_preferences)],
    user: AuthenticatedUser = Depends(get_current_user),
) -> ReminderResponse:
    """
    Create a new reminder.

    Args:
        request: Reminder creation request

    Returns:
        Created reminder details

    Raises:
        HTTPException: If validation fails or creation errors occur
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(
            user={"id": user_id},
            reminder=ReminderContext(operation="create"),
        )

        # The schedule runs in the user's HOME zone (DB profile, healed from the
        # x-timezone header), so recurring reminders fire at the right local hour
        # — and the same default as workflows, regardless of current location.
        reminder_data.timezone = user_timezone

        # Create the reminder
        reminder_id = await reminder_scheduler.create_reminder(
            reminder_data=reminder_data, user_id=user_id
        )

        # Retrieve and return created reminder
        reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)
        if not reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve created reminder",
            )

        log.set(reminder=_reminder_context("create", reminder))
        log.set(outcome="success")

        capture_context_event(
            AnalyticsEvents.REMINDER_CREATED, {"is_recurring": bool(reminder.repeat)}
        )
        return ReminderResponse.model_validate(reminder)

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error creating reminder",
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create reminder",
        ) from e


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder_endpoint(
    reminder_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> ReminderResponse:
    """
    Get a reminder by ID.

    Args:
        reminder_id: Reminder ID

    Returns:
        Reminder details

    Raises:
        HTTPException: If reminder not found or access denied
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(
            user={"id": user_id},
            reminder=ReminderContext(operation="get", id=reminder_id),
        )

        reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)

        if not reminder:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Reminder {reminder_id} not found",
            )

        log.set(reminder=_reminder_context("get", reminder))
        log.set(outcome="success")

        return ReminderResponse.model_validate(reminder)

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error getting reminder",
            reminder_id=reminder_id,
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reminder",
        ) from e


@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder_endpoint(
    reminder_id: str,
    request: UpdateReminderRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ReminderResponse:
    """
    Update an existing reminder.

    Args:
        reminder_id: Reminder ID
        request: Reminder update request

    Returns:
        Updated reminder details

    Raises:
        HTTPException: If reminder not found or validation fails
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(
            user={"id": user_id},
            reminder=ReminderContext(operation="update", id=reminder_id),
        )

        # exclude_none keeps an omitted field out of `model_fields_set`, so the
        # repository's `$set` only touches what the caller actually sent.
        update = ReminderUpdate(**request.model_dump(exclude_none=True))

        # Update reminder
        success = await reminder_scheduler.update_reminder(
            reminder_id, user_id=user_id, update=update
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        log.set(reminder=_reminder_context("update", updated_reminder))
        log.set(outcome="success")

        return ReminderResponse.model_validate(updated_reminder)

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error updating reminder",
            reminder_id=reminder_id,
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update reminder",
        ) from e


@router.delete("/{reminder_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def cancel_reminder_endpoint(
    reminder_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> None:
    """
    Cancel a reminder.

    Args:
        reminder_id: Reminder ID

    Raises:
        HTTPException: If reminder not found or access denied
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(
            user={"id": user_id},
            reminder=ReminderContext(operation="delete", id=reminder_id),
        )

        success = await reminder_scheduler.cancel_task(reminder_id, user_id=user_id)

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel reminder",
            )

        capture_context_event(AnalyticsEvents.REMINDER_DELETED)
        log.set(outcome="success")

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error cancelling reminder",
            reminder_id=reminder_id,
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel reminder",
        ) from e


@router.get("", response_model=list[ReminderResponse])
async def list_reminders_endpoint(
    user: AuthenticatedUser = Depends(get_current_user),
    status: ReminderStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip"),
) -> list[ReminderResponse]:
    """
    List reminders for a user.

    Args:
        status: Optional status filter
        reminder_type: Optional type filter
        limit: Maximum number of results
        skip: Number of results to skip

    Returns:
        List of reminders
    """
    user_id = user.get("user_id")
    try:
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(
            user={"id": user_id},
            reminder=ReminderContext(operation="list"),
        )

        reminders = await reminder_scheduler.list_user_reminders(
            user_id=user_id,
            status=status,
            limit=limit,
            skip=skip,
        )

        log.set(
            reminder=ReminderContext(
                operation="list",
                result_count=len(reminders),
            )
        )
        log.set(outcome="success")

        return [ReminderResponse.model_validate(reminder) for reminder in reminders]

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error listing reminders",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list reminders",
        ) from e


@router.post("/{reminder_id}/pause", response_model=ReminderResponse)
async def pause_reminder_endpoint(
    reminder_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> ReminderResponse:
    """
    Pause a reminder.

    Args:
        reminder_id: Reminder ID

    Returns:
        Updated reminder details

    Raises:
        HTTPException: If reminder not found or access denied
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(user={"id": user_id}, reminder={"id": reminder_id})

        # Update status to paused
        success = await reminder_scheduler.update_reminder(
            reminder_id, ReminderUpdate(status=ReminderStatus.PAUSED), user_id=user_id
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to pause reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        return ReminderResponse.model_validate(updated_reminder)

    except HTTPException:
        raise  # let a deliberate 404/4xx from the service through, not masked as 500
    except Exception as e:
        log.error(
            f"{LogTag.API} Error pausing reminder",
            reminder_id=reminder_id,
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause reminder",
        ) from e


@router.post("/{reminder_id}/resume", response_model=ReminderResponse)
async def resume_reminder_endpoint(
    reminder_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> ReminderResponse:
    """
    Resume a paused reminder.

    Args:
        reminder_id: Reminder ID

    Returns:
        Updated reminder details

    Raises:
        HTTPException: If reminder not found or access denied
    """
    try:
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        log.set(user={"id": user_id}, reminder={"id": reminder_id})

        # Check if reminder exists and user owns it
        existing_reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)
        if not existing_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Reminder {reminder_id} not found",
            )

        if existing_reminder.status != ReminderStatus.PAUSED:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Reminder {reminder_id} is not paused (current status: {existing_reminder.status})",
            )

        # Update status to scheduled and reschedule if needed
        update = ReminderUpdate(status=ReminderStatus.SCHEDULED)

        # If it's a recurring reminder, calculate next run time
        if existing_reminder.repeat:
            update.scheduled_at = get_next_run_time(existing_reminder.repeat)

        success = await reminder_scheduler.update_reminder(reminder_id, update, user_id=user_id)

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resume reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        return ReminderResponse(**updated_reminder.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.API} Error resuming reminder",
            reminder_id=reminder_id,
            user_id=user.get("user_id"),
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume reminder",
        ) from e


@router.get("/cron/validate")
async def validate_cron_endpoint(
    expression: str = Query(..., description="Cron expression to validate"),
) -> CronValidationResponse:
    """Validate a cron expression and preview its next few run times."""
    log.set(reminder=ReminderContext(operation="validate_cron"))
    try:
        is_valid = validate_cron_expression(expression)
        if not is_valid:
            return CronValidationResponse(expression=expression, valid=False)

        next_runs = calculate_next_occurrences(expression, _CRON_PREVIEW_RUNS)
        return CronValidationResponse(
            expression=expression,
            valid=True,
            next_runs=[run.isoformat() for run in next_runs],
        )

    except Exception as e:
        log.error(
            f"{LogTag.API} Error validating cron expression",
            expression=expression,
            error_type=type(e).__name__,
            error=str(e),
        )
        return CronValidationResponse(expression=expression, valid=False, error=str(e))
