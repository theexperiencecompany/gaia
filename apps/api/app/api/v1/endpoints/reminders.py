"""
FastAPI endpoints for reminder management.
"""

from typing import List, Optional

from app.api.v1.dependencies.oauth_dependencies import (
    GET_USER_TZ_TYPE,
    get_current_user,
    get_user_timezone,
)
from app.config.loggers import general_logger as logger
from app.decorators import tiered_rate_limit
from app.models.reminder_models import (
    CreateReminderRequest,
    ReminderResponse,
    ReminderStatus,
    UpdateReminderRequest,
)
from app.services.reminder_service import reminder_scheduler
from app.utils.cron_utils import get_next_run_time, validate_cron_expression
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post(
    "", response_model=ReminderResponse, status_code=http_status.HTTP_201_CREATED
)
@tiered_rate_limit("reminder_operations")
async def create_reminder_endpoint(
    reminder_data: CreateReminderRequest,
    user: dict = Depends(get_current_user),
    tz_info: GET_USER_TZ_TYPE = Depends(get_user_timezone),
):
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

        # Prepare reminder data
        reminder_data.base_time = tz_info[1]  # Use user's current time

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

        return ReminderResponse(**reminder.model_dump())

    except Exception as e:
        logger.error(f"Error creating reminder: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create reminder",
        )


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder_endpoint(
    reminder_id: str, user: dict = Depends(get_current_user)
):
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

        reminder = await reminder_scheduler.get_reminder(reminder_id, user_id=user_id)

        if not reminder:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Reminder {reminder_id} not found",
            )

        return ReminderResponse(**reminder.model_dump())

    except Exception as e:
        logger.error(f"Error getting reminder {reminder_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reminder",
        )


@router.put("/{reminder_id}", response_model=ReminderResponse)
async def update_reminder_endpoint(
    reminder_id: str,
    request: UpdateReminderRequest,
    user: dict = Depends(get_current_user),
):
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

        # Prepare update data
        update_data = request.model_dump(exclude_none=True)

        # Update reminder
        success = await reminder_scheduler.update_reminder(
            reminder_id, user_id=user_id, update_data=update_data
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(
            reminder_id, user_id=user_id
        )
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        return ReminderResponse(**updated_reminder.model_dump())

    except Exception as e:
        logger.error(f"Error updating reminder {reminder_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update reminder",
        )


@router.delete("/{reminder_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def cancel_reminder_endpoint(
    reminder_id: str, user: dict = Depends(get_current_user)
):
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

        success = await reminder_scheduler.cancel_task(reminder_id, user_id=user_id)

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel reminder",
            )

    except Exception as e:
        logger.error(f"Error cancelling reminder {reminder_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel reminder",
        )


@router.get("", response_model=List[ReminderResponse])
async def list_reminders_endpoint(
    user: dict = Depends(get_current_user),
    status: Optional[ReminderStatus] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    skip: int = Query(0, ge=0, description="Number of results to skip"),
):
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

        reminders = await reminder_scheduler.list_user_reminders(
            user_id=user_id,
            status=status,
            limit=limit,
            skip=skip,
        )

        return [ReminderResponse(**reminder.model_dump()) for reminder in reminders]

    except Exception as e:
        logger.error(f"Error listing reminders for user {user_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list reminders",
        )


@router.post("/{reminder_id}/pause", response_model=ReminderResponse)
async def pause_reminder_endpoint(
    reminder_id: str, user: dict = Depends(get_current_user)
):
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

        # Update status to paused
        success = await reminder_scheduler.update_reminder(
            reminder_id, {"status": ReminderStatus.PAUSED}, user_id=user_id
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to pause reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(
            reminder_id, user_id=user_id
        )
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        return ReminderResponse(**updated_reminder.model_dump())

    except Exception as e:
        logger.error(f"Error pausing reminder {reminder_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause reminder",
        )


@router.post("/{reminder_id}/resume", response_model=ReminderResponse)
async def resume_reminder_endpoint(
    reminder_id: str, user: dict = Depends(get_current_user)
):
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

        # Check if reminder exists and user owns it
        existing_reminder = await reminder_scheduler.get_reminder(
            reminder_id, user_id=user_id
        )
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
        update_data: dict = {"status": ReminderStatus.SCHEDULED}

        # If it's a recurring reminder, calculate next run time
        if existing_reminder.repeat:
            next_run = get_next_run_time(existing_reminder.repeat)
            update_data["scheduled_at"] = next_run

        success = await reminder_scheduler.update_reminder(
            reminder_id, update_data, user_id=user_id
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to resume reminder",
            )

        # Get updated reminder
        updated_reminder = await reminder_scheduler.get_reminder(
            reminder_id, user_id=user_id
        )
        if not updated_reminder:
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve updated reminder",
            )

        return ReminderResponse(**updated_reminder.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming reminder {reminder_id}: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resume reminder",
        )


@router.get("/cron/validate")
async def validate_cron_endpoint(
    expression: str = Query(..., description="Cron expression to validate"),
):
    """
    Validate a cron expression.

    Args:
        expression: Cron expression to validate

    Returns:
        Validation result
    """
    try:
        is_valid = validate_cron_expression(expression)

        result = {"expression": expression, "valid": is_valid}

        if is_valid:
            # Get next few run times as examples
            from app.utils.cron_utils import calculate_next_occurrences

            next_runs = calculate_next_occurrences(expression, 5)
            result["next_runs"] = [run.isoformat() for run in next_runs]

        return result

    except Exception as e:
        logger.error(f"Error validating cron expression {expression}: {e}")
        return {"expression": expression, "valid": False, "error": str(e)}
