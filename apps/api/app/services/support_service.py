"""Support service for handling support requests and email notifications."""

import asyncio
from datetime import UTC, datetime
import uuid

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile

from app.db.repositories.support_requests import support_request_repository
from app.models.support_models import (
    SupportAttachment,
    SupportEmailNotification,
    SupportRequestCreate,
    SupportRequestDocument,
    SupportRequestListResponse,
    SupportRequestPagination,
    SupportRequestPriority,
    SupportRequestResponse,
    SupportRequestStatus,
    SupportRequestSubmissionResponse,
)
from app.services.email import (
    send_support_team_notification,
    send_support_to_user_email,
)
from app.services.upload_service import upload_file_to_cloudinary
from shared.py.wide_events import log

# Support team emails
SUPPORT_EMAILS = [
    "support@heygaia.io",
    "aryan@heygaia.io",
]


async def _delete_uploaded_files(attachment_urls: list[str]) -> None:
    """Delete uploaded files from Cloudinary."""
    for url in attachment_urls:
        try:
            # Extract filename from URL to construct public_id
            # URL format: https://res.cloudinary.com/.../support/{ticket_id}_{filename}
            url_parts = url.split("/")
            if "support" in url_parts:
                # Find the filename part after 'support/'
                support_index = url_parts.index("support")
                if support_index + 1 < len(url_parts):
                    filename_with_ext = url_parts[support_index + 1]
                    # The file is named {ticket_id}_{original_name}; the ticket
                    # id rides in the URL so a failed delete stays attributable.
                    ticket_id = filename_with_ext.split("_", 1)[0]
                    # Remove file extension from public_id
                    public_id = f"support/{filename_with_ext.rsplit('.', 1)[0]}"

                    # Cloudinary's SDK is blocking HTTP — off the loop, or every
                    # other request on this worker waits out the round trip.
                    result = await asyncio.to_thread(cloudinary.uploader.destroy, public_id)
                    if result.get("result") != "ok":
                        log.warning(
                            "Failed to delete file from Cloudinary",
                            public_id=public_id,
                        )
                    else:
                        log.info("Successfully deleted file from Cloudinary", public_id=public_id)
        except Exception as e:
            log.error(
                "Error deleting file from Cloudinary",
                url=url,
                ticket_id=ticket_id,
                error=str(e),
                error_type=type(e).__name__,
            )


async def _upload_single_attachment(
    attachment: UploadFile,
    ticket_id: str,
    current_time: datetime,
    allowed_types: list[str],
    max_file_size: int,
) -> tuple[str, SupportAttachment]:
    """Upload a single attachment and return (file_url, attachment metadata)."""
    # Validate file type
    if attachment.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Only image files are supported. File type {attachment.content_type} not allowed. Please use JPG, PNG, or WebP.",
        )

    # Validate filename
    if not attachment.filename:
        raise HTTPException(status_code=400, detail="All images must have filenames")

    # Read and validate file size
    content = await attachment.read()
    if len(content) > max_file_size:
        raise HTTPException(
            status_code=400,
            detail=f"File {attachment.filename} exceeds maximum size of 10MB",
        )

    # Upload to Cloudinary
    public_id = f"support/{ticket_id}_{attachment.filename}"
    try:
        # Run the synchronous upload function in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        file_url = await loop.run_in_executor(
            None,
            lambda: upload_file_to_cloudinary(public_id=public_id, file_data=content),
        )

        # Create attachment metadata
        attachment_info = SupportAttachment(
            filename=attachment.filename,
            file_size=len(content),
            content_type=attachment.content_type or "application/octet-stream",
            file_url=file_url,
            uploaded_at=current_time,
        )

        return file_url, attachment_info

    except Exception as e:
        log.error(
            "Failed to upload image",
            filename=attachment.filename,
            error=str(e),
            error_type=type(e).__name__,
            ticket_id=ticket_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image {attachment.filename}",
        )


async def create_support_request(
    request_data: SupportRequestCreate,
    user_id: str,
    user_email: str,
    user_name: str | None = None,
) -> SupportRequestSubmissionResponse:
    """Create a new support request and send email notifications.

    Atomic: if email sending fails, the support request is deleted.
    """
    log.set(component="support_service", user_id=user_id, user_email=user_email)
    request_id = None
    try:
        # Generate unique IDs
        request_id = str(uuid.uuid4())
        ticket_id = f"GAIA-{datetime.now(UTC).strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        current_time = datetime.now(UTC)

        # Create support request document
        support_request = SupportRequestDocument(
            id=request_id,
            ticket_id=ticket_id,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            type=request_data.type,
            title=request_data.title,
            description=request_data.description,
            priority=SupportRequestPriority.MEDIUM,
            created_at=current_time,
            metadata={
                "source": "web_form",
                "user_agent": None,  # Could be added from request headers
            },
        )

        # Store in database first
        created = await support_request_repository.create(support_request)

        log.info("Support request created in database", ticket_id=ticket_id)

        # Try to send email notifications
        try:
            await _send_support_email_notifications(
                SupportEmailNotification(
                    user_name=user_name or "User",
                    user_email=user_email,
                    ticket_id=ticket_id,
                    type=request_data.type,
                    title=request_data.title,
                    description=request_data.description,
                    created_at=current_time,
                    support_emails=SUPPORT_EMAILS,
                    attachments=[],
                )
            )
            log.info("Email notifications sent successfully for ticket", ticket_id=ticket_id)
        except Exception as email_error:
            # Email sending failed - rollback the database transaction
            log.error(
                "Email sending failed for ticket",
                ticket_id=ticket_id,
                error=str(email_error),
                error_type=type(email_error).__name__,
                user_id=user_id,
            )

            try:
                # Delete the support request from database
                if await support_request_repository.delete(request_id, user_id=user_id):
                    log.info(
                        "Successfully rolled back support request from database",
                        ticket_id=ticket_id,
                    )
                else:
                    log.error(
                        "Failed to rollback support request from database",
                        ticket_id=ticket_id,
                        error=str(email_error),
                        error_type=type(email_error).__name__,
                        user_id=user_id,
                    )
            except Exception as rollback_error:
                log.error(
                    "Error during rollback for ticket",
                    ticket_id=ticket_id,
                    error=str(rollback_error),
                    error_type=type(rollback_error).__name__,
                    user_id=user_id,
                )

            # Raise the original email error
            raise HTTPException(
                status_code=500,
                detail="Failed to send email notifications. Support request was not created. Please try again.",
            )

        # Create response object
        support_request_response = SupportRequestResponse.model_validate(created.model_dump())

        log.info(
            "Support request created successfully: for user", ticket_id=ticket_id, user_id=user_id
        )

        return SupportRequestSubmissionResponse(
            success=True,
            message="Support request submitted successfully. You will receive an email confirmation shortly.",
            ticket_id=ticket_id,
            support_request=support_request_response,
        )

    except HTTPException:
        # Re-raise HTTP exceptions without wrapping
        raise
    except Exception as e:
        # For any other unexpected errors, also try to rollback if request was created
        if request_id:
            try:
                await support_request_repository.delete(request_id, user_id=user_id)
                log.info(
                    "Rolled back support request due to unexpected error", request_id=request_id
                )
            except Exception as rollback_error:
                log.error(
                    "Error during rollback for request",
                    request_id=request_id,
                    error=str(rollback_error),
                    error_type=type(rollback_error).__name__,
                    user_id=user_id,
                )

        log.error(
            "Unexpected error creating support request",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(status_code=500, detail=f"Failed to create support request: {e!s}")


async def create_support_request_with_attachments(
    request_data: SupportRequestCreate,
    attachments: list[UploadFile],
    user_id: str,
    user_email: str,
    user_name: str | None = None,
) -> SupportRequestSubmissionResponse:
    """Create a new support request with file attachments and send email notifications.

    Atomic: if email sending fails, the support request and uploaded files are deleted.
    """
    log.set(
        component="support_service",
        user_id=user_id,
        user_email=user_email,
        attachment_count=len(attachments),
    )
    request_id = None
    attachment_urls: list[str] = []
    ticket_id = None

    try:
        # Generate unique IDs
        request_id = str(uuid.uuid4())
        ticket_id = f"GAIA-{datetime.now(UTC).strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

        current_time = datetime.now(UTC)

        # Process attachments
        processed_attachments: list[SupportAttachment] = []

        if attachments:
            # Validate file constraints
            ALLOWED_TYPES = [
                "image/jpeg",
                "image/jpg",
                "image/png",
                "image/webp",
            ]
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
            MAX_ATTACHMENTS = 5

            if len(attachments) > MAX_ATTACHMENTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum {MAX_ATTACHMENTS} images allowed",
                )

            # Upload all files in parallel using asyncio.gather()
            try:
                upload_tasks = [
                    _upload_single_attachment(
                        attachment=attachment,
                        ticket_id=ticket_id,
                        current_time=current_time,
                        allowed_types=ALLOWED_TYPES,
                        max_file_size=MAX_FILE_SIZE,
                    )
                    for attachment in attachments
                ]

                # Execute all uploads in parallel
                upload_results = await asyncio.gather(*upload_tasks)

                # Extract URLs and attachment metadata from results
                for file_url, attachment_metadata in upload_results:
                    attachment_urls.append(file_url)
                    processed_attachments.append(attachment_metadata)

                log.info(
                    "Successfully uploaded files in parallel for ticket",
                    attachment_urls_count=len(attachment_urls),
                    ticket_id=ticket_id,
                )

            except Exception:
                # Clean up any files that were successfully uploaded before the failure
                if attachment_urls:
                    log.info(
                        "Cleaning up partially uploaded files for ticket",
                        attachment_urls_count=len(attachment_urls),
                        ticket_id=ticket_id,
                    )
                    await _delete_uploaded_files(attachment_urls)

                # Re-raise the original exception (could be HTTPException from validation or upload error)
                raise

        # Create support request document
        support_request = SupportRequestDocument(
            id=request_id,
            ticket_id=ticket_id,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            type=request_data.type,
            title=request_data.title,
            description=request_data.description,
            priority=SupportRequestPriority.MEDIUM,
            created_at=current_time,
            attachments=processed_attachments,
            metadata={
                "source": "web_form_with_images",
                "user_agent": None,
                "image_count": len(processed_attachments),
            },
        )

        # Store in database first
        created = await support_request_repository.create(support_request)

        log.info("Support request with attachments created in database", ticket_id=ticket_id)

        # Try to send email notifications
        try:
            notification_data = SupportEmailNotification(
                user_name=user_name or "User",
                user_email=user_email,
                ticket_id=ticket_id,
                type=request_data.type,
                title=request_data.title,
                description=request_data.description,
                created_at=current_time,
                support_emails=SUPPORT_EMAILS,
                attachments=processed_attachments,
            )

            await _send_support_email_notifications(notification_data)
            log.info("Email notifications sent successfully for ticket", ticket_id=ticket_id)
        except Exception as email_error:
            # Email sending failed - rollback everything
            log.error(
                "Email sending failed for ticket",
                ticket_id=ticket_id,
                error=str(email_error),
                error_type=type(email_error).__name__,
                user_id=user_id,
            )

            # Rollback: Delete uploaded files
            if attachment_urls:
                try:
                    await _delete_uploaded_files(attachment_urls)
                    log.info(
                        "Successfully cleaned up uploaded files for ticket",
                        attachment_urls_count=len(attachment_urls),
                        ticket_id=ticket_id,
                    )
                except Exception as cleanup_error:
                    log.error(
                        "Error cleaning up uploaded files for ticket",
                        ticket_id=ticket_id,
                        error=str(cleanup_error),
                        error_type=type(cleanup_error).__name__,
                        user_id=user_id,
                    )

            # Rollback: Delete the support request from database
            try:
                if await support_request_repository.delete(request_id, user_id=user_id):
                    log.info(
                        "Successfully rolled back support request from database",
                        ticket_id=ticket_id,
                    )
                else:
                    log.error(
                        "Failed to rollback support request from database",
                        ticket_id=ticket_id,
                        error=str(email_error),
                        error_type=type(email_error).__name__,
                        user_id=user_id,
                    )
            except Exception as rollback_error:
                log.error(
                    "Error during database rollback for ticket",
                    ticket_id=ticket_id,
                    error=str(rollback_error),
                    error_type=type(rollback_error).__name__,
                    user_id=user_id,
                )

            # Raise the original email error
            raise HTTPException(
                status_code=500,
                detail="Failed to send email notifications. Support request was not created. Please try again.",
            )

        # Create response object
        support_request_response = SupportRequestResponse.model_validate(created.model_dump())

        log.info(
            "Support request with images created successfully: for user",
            processed_attachments_count=len(processed_attachments),
            ticket_id=ticket_id,
            user_id=user_id,
        )

        return SupportRequestSubmissionResponse(
            success=True,
            message="Support request with images submitted successfully. You will receive an email confirmation shortly.",
            ticket_id=ticket_id,
            support_request=support_request_response,
        )

    except HTTPException:
        # Re-raise HTTP exceptions without additional cleanup (already handled above)
        raise
    except Exception as e:
        # For any other unexpected errors, also try to rollback everything
        log.error(
            "Unexpected error creating support request with images",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

        # Clean up uploaded files
        if attachment_urls and ticket_id:
            try:
                await _delete_uploaded_files(attachment_urls)
                log.info(
                    "Cleaned up uploaded files due to unexpected error",
                    attachment_urls_count=len(attachment_urls),
                )
            except Exception as cleanup_error:
                log.error(
                    "Error cleaning up uploaded files",
                    error=str(cleanup_error),
                    error_type=type(cleanup_error).__name__,
                    user_id=user_id,
                )

        # Clean up database entry
        if request_id:
            try:
                await support_request_repository.delete(request_id, user_id=user_id)
                log.info(
                    "Rolled back support request due to unexpected error", request_id=request_id
                )
            except Exception as rollback_error:
                log.error(
                    "Error during rollback for request",
                    request_id=request_id,
                    error=str(rollback_error),
                    error_type=type(rollback_error).__name__,
                    user_id=user_id,
                )

        raise HTTPException(status_code=500, detail=f"Failed to create support request: {e!s}")


async def _send_support_email_notifications(
    notification_data: SupportEmailNotification,
) -> None:
    """Send email notifications to the support team and the user.

    Raises on failure so the caller can roll back the transaction.
    """
    try:
        # Send to support team
        await send_support_team_notification(notification_data)

        # Send support to user email
        await send_support_to_user_email(notification_data)

    except Exception as e:
        log.error("Error sending email notifications", error=str(e), error_type=type(e).__name__)
        # Re-raise to trigger transaction rollback
        raise


async def get_user_support_requests(
    user_id: str,
    page: int = 1,
    per_page: int = 10,
    status_filter: SupportRequestStatus | None = None,
) -> SupportRequestListResponse:
    """Get paginated support requests for a user."""
    try:
        skip = (page - 1) * per_page

        total = await support_request_repository.count_for_user_status(
            user_id, status=status_filter
        )
        docs = await support_request_repository.page_for_user(
            user_id, status=status_filter, skip=skip, limit=per_page
        )

        support_requests = [SupportRequestResponse.model_validate(doc.model_dump()) for doc in docs]

        return SupportRequestListResponse(
            requests=support_requests,
            pagination=SupportRequestPagination(
                page=page,
                per_page=per_page,
                total=total,
                pages=(total + per_page - 1) // per_page,
            ),
        )

    except Exception as e:
        log.error(
            "Error fetching user support requests",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(status_code=500, detail="Failed to fetch support requests")
