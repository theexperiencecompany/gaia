"""Support service for handling support requests and email notifications."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cloudinary
import cloudinary.uploader
from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import support_collection
from app.models.support_models import (
    SupportAttachment,
    SupportEmailNotification,
    SupportRequestCreate,
    SupportRequestPriority,
    SupportRequestResponse,
    SupportRequestStatus,
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
from app.services.upload_service import upload_file_to_cloudinary
from app.utils.email_utils import (
    send_support_team_notification,
    send_support_to_user_email,
)
from fastapi import HTTPException, UploadFile

# Support team emails
SUPPORT_EMAILS = [
    "support@heygaia.io",
    "aryan@heygaia.io",
]


async def _delete_uploaded_files(attachment_urls: List[str], ticket_id: str) -> None:
    """Delete uploaded files from Cloudinary.

    Args:
        attachment_urls: List of file URLs to delete
        ticket_id: Ticket ID used to construct public_ids
    """
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
                    # Remove file extension from public_id
                    public_id = f"support/{filename_with_ext.rsplit('.', 1)[0]}"

                    result = cloudinary.uploader.destroy(public_id)
                    if result.get("result") != "ok":
                        logger.warning(
                            f"Failed to delete file from Cloudinary: {public_id}"
                        )
                    else:
                        logger.info(
                            f"Successfully deleted file from Cloudinary: {public_id}"
                        )
        except Exception as e:
            logger.error(f"Error deleting file from Cloudinary {url}: {str(e)}")


async def _upload_single_attachment(
    attachment: UploadFile,
    ticket_id: str,
    current_time: datetime,
    allowed_types: List[str],
    max_file_size: int,
) -> tuple[str, dict]:
    """
    Upload a single attachment file and return its URL and metadata.

    Args:
        attachment: The file to upload
        ticket_id: Ticket ID for public_id construction
        current_time: Current timestamp
        allowed_types: List of allowed content types
        max_file_size: Maximum file size in bytes

    Returns:
        Tuple of (file_url, attachment_metadata_dict)

    Raises:
        HTTPException: If validation or upload fails
    """
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

        return file_url, attachment_info.dict()

    except Exception as e:
        logger.error(f"Failed to upload image {attachment.filename}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image {attachment.filename}",
        )


async def create_support_request(
    request_data: SupportRequestCreate,
    user_id: str,
    user_email: str,
    user_name: Optional[str] = None,
) -> SupportRequestSubmissionResponse:
    """
    Create a new support request and send email notifications.
    Implements atomic transaction: if email sending fails, the support request is deleted.

    Args:
        request_data: Support request data
        user_id: ID of the user creating the request
        user_email: Email of the user
        user_name: Name of the user (optional)

    Returns:
        SupportRequestSubmissionResponse with success status and ticket ID
    """
    request_id = None
    try:
        # Generate unique IDs
        request_id = str(uuid.uuid4())
        ticket_id = (
            f"GAIA-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        )

        current_time = datetime.now(timezone.utc)

        # Create support request document
        support_request_doc: Dict[str, Any] = {
            "_id": request_id,
            "ticket_id": ticket_id,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "type": request_data.type.value,
            "title": request_data.title,
            "description": request_data.description,
            "status": SupportRequestStatus.OPEN.value,
            "priority": SupportRequestPriority.MEDIUM.value,  # Default priority
            "created_at": current_time,
            "updated_at": current_time,
            "resolved_at": None,
            "tags": [],
            "metadata": {
                "source": "web_form",
                "user_agent": None,  # Could be added from request headers
            },
        }

        # Store in database first
        result = await support_collection.insert_one(support_request_doc)

        if not result.inserted_id:
            raise HTTPException(
                status_code=500, detail="Failed to create support request"
            )

        logger.info(f"Support request created in database: {ticket_id}")

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
            logger.info(
                f"Email notifications sent successfully for ticket: {ticket_id}"
            )
        except Exception as email_error:
            # Email sending failed - rollback the database transaction
            logger.error(
                f"Email sending failed for ticket {ticket_id}: {str(email_error)}"
            )

            try:
                # Delete the support request from database
                delete_result = await support_collection.delete_one({"_id": request_id})
                if delete_result.deleted_count > 0:
                    logger.info(
                        f"Successfully rolled back support request {ticket_id} from database"
                    )
                else:
                    logger.error(
                        f"Failed to rollback support request {ticket_id} from database"
                    )
            except Exception as rollback_error:
                logger.error(
                    f"Error during rollback for ticket {ticket_id}: {str(rollback_error)}"
                )

            # Raise the original email error
            raise HTTPException(
                status_code=500,
                detail="Failed to send email notifications. Support request was not created. Please try again.",
            )

        # Create response object
        support_request_response = SupportRequestResponse(
            id=request_id,
            ticket_id=ticket_id,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            type=request_data.type,
            title=request_data.title,
            description=request_data.description,
            status=SupportRequestStatus.OPEN,
            priority=SupportRequestPriority.MEDIUM,
            created_at=current_time,
            updated_at=current_time,
            resolved_at=None,
            tags=[],
            metadata=dict(support_request_doc["metadata"]),
        )

        logger.info(
            f"Support request created successfully: {ticket_id} for user {user_id}"
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
                await support_collection.delete_one({"_id": request_id})
                logger.info(
                    f"Rolled back support request {request_id} due to unexpected error"
                )
            except Exception as rollback_error:
                logger.error(
                    f"Error during rollback for request {request_id}: {str(rollback_error)}"
                )

        logger.error(f"Unexpected error creating support request: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create support request: {str(e)}"
        )


async def create_support_request_with_attachments(
    request_data: SupportRequestCreate,
    attachments: List[UploadFile],
    user_id: str,
    user_email: str,
    user_name: Optional[str] = None,
) -> SupportRequestSubmissionResponse:
    """
    Create a new support request with file attachments and send email notifications.
    Implements atomic transaction: if email sending fails, the support request and uploaded files are deleted.

    Args:
        request_data: Support request data
        attachments: List of uploaded files
        user_id: ID of the user creating the request
        user_email: Email of the user
        user_name: Name of the user (optional)

    Returns:
        SupportRequestSubmissionResponse with success status and ticket ID
    """
    request_id = None
    attachment_urls = []
    ticket_id = None

    try:
        # Generate unique IDs
        request_id = str(uuid.uuid4())
        ticket_id = (
            f"GAIA-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        )

        current_time = datetime.now(timezone.utc)

        # Process attachments
        processed_attachments = []

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

                logger.info(
                    f"Successfully uploaded {len(attachment_urls)} files in parallel for ticket {ticket_id}"
                )

            except Exception:
                # Clean up any files that were successfully uploaded before the failure
                if attachment_urls:
                    logger.info(
                        f"Cleaning up {len(attachment_urls)} partially uploaded files for ticket {ticket_id}"
                    )
                    await _delete_uploaded_files(attachment_urls, ticket_id)

                # Re-raise the original exception (could be HTTPException from validation or upload error)
                raise

        # Create support request document
        support_request_doc = {
            "_id": request_id,
            "ticket_id": ticket_id,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "type": request_data.type.value,
            "title": request_data.title,
            "description": request_data.description,
            "status": SupportRequestStatus.OPEN.value,
            "priority": SupportRequestPriority.MEDIUM.value,
            "created_at": current_time,
            "updated_at": current_time,
            "resolved_at": None,
            "tags": [],
            "attachments": processed_attachments,
            "metadata": {
                "source": "web_form_with_images",
                "user_agent": None,
                "image_count": len(processed_attachments),
            },
        }

        # Store in database first
        result = await support_collection.insert_one(support_request_doc)

        if not result.inserted_id:
            # Clean up uploaded files if database insertion fails
            if attachment_urls:
                await _delete_uploaded_files(attachment_urls, ticket_id)
            raise HTTPException(
                status_code=500, detail="Failed to create support request"
            )

        logger.info(
            f"Support request with attachments created in database: {ticket_id}"
        )

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
                attachments=[SupportAttachment(**att) for att in processed_attachments],
            )

            await _send_support_email_notifications(notification_data)
            logger.info(
                f"Email notifications sent successfully for ticket: {ticket_id}"
            )
        except Exception as email_error:
            # Email sending failed - rollback everything
            logger.error(
                f"Email sending failed for ticket {ticket_id}: {str(email_error)}"
            )

            # Rollback: Delete uploaded files
            if attachment_urls:
                try:
                    await _delete_uploaded_files(attachment_urls, ticket_id)
                    logger.info(
                        f"Successfully cleaned up {len(attachment_urls)} uploaded files for ticket {ticket_id}"
                    )
                except Exception as cleanup_error:
                    logger.error(
                        f"Error cleaning up uploaded files for ticket {ticket_id}: {str(cleanup_error)}"
                    )

            # Rollback: Delete the support request from database
            try:
                delete_result = await support_collection.delete_one({"_id": request_id})
                if delete_result.deleted_count > 0:
                    logger.info(
                        f"Successfully rolled back support request {ticket_id} from database"
                    )
                else:
                    logger.error(
                        f"Failed to rollback support request {ticket_id} from database"
                    )
            except Exception as rollback_error:
                logger.error(
                    f"Error during database rollback for ticket {ticket_id}: {str(rollback_error)}"
                )

            # Raise the original email error
            raise HTTPException(
                status_code=500,
                detail="Failed to send email notifications. Support request was not created. Please try again.",
            )

        # Create response object
        support_request_response = SupportRequestResponse(
            id=request_id,
            ticket_id=ticket_id,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            type=request_data.type,
            title=request_data.title,
            description=request_data.description,
            status=SupportRequestStatus.OPEN,
            priority=SupportRequestPriority.MEDIUM,
            created_at=current_time,
            updated_at=current_time,
            resolved_at=None,
            tags=[],
            attachments=[SupportAttachment(**att) for att in processed_attachments],
            metadata=support_request_doc["metadata"]
            if isinstance(support_request_doc["metadata"], dict)
            else {},
        )

        logger.info(
            f"Support request with {len(processed_attachments)} images created successfully: {ticket_id} for user {user_id}"
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
        logger.error(f"Unexpected error creating support request with images: {str(e)}")

        # Clean up uploaded files
        if attachment_urls and ticket_id:
            try:
                await _delete_uploaded_files(attachment_urls, ticket_id)
                logger.info(
                    f"Cleaned up {len(attachment_urls)} uploaded files due to unexpected error"
                )
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up uploaded files: {str(cleanup_error)}")

        # Clean up database entry
        if request_id:
            try:
                await support_collection.delete_one({"_id": request_id})
                logger.info(
                    f"Rolled back support request {request_id} due to unexpected error"
                )
            except Exception as rollback_error:
                logger.error(
                    f"Error during rollback for request {request_id}: {str(rollback_error)}"
                )

        raise HTTPException(
            status_code=500, detail=f"Failed to create support request: {str(e)}"
        )


async def _send_support_email_notifications(
    notification_data: SupportEmailNotification,
) -> None:
    """
    Send email notifications to support team and support to user.
    Raises exception if email sending fails to allow for transaction rollback.

    Args:
        notification_data: Email notification data

    Raises:
        Exception: If email sending fails
    """
    try:
        # Send to support team
        await send_support_team_notification(notification_data)

        # Send support to user email
        await send_support_to_user_email(notification_data)

    except Exception as e:
        logger.error(f"Error sending email notifications: {str(e)}")
        # Re-raise the exception to trigger transaction rollback
        raise e


async def get_user_support_requests(
    user_id: str,
    page: int = 1,
    per_page: int = 10,
    status_filter: Optional[SupportRequestStatus] = None,
) -> Dict:
    """
    Get support requests for a specific user.

    Args:
        user_id: ID of the user
        page: Page number for pagination
        per_page: Number of items per page
        status_filter: Optional status filter

    Returns:
        Dictionary with support requests and pagination info
    """
    try:
        query = {"user_id": user_id}
        if status_filter:
            query["status"] = status_filter.value

        # Count total documents
        total = await support_collection.count_documents(query)

        # Calculate pagination
        skip = (page - 1) * per_page

        # Fetch documents
        cursor = (
            support_collection.find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(per_page)
        )
        requests = await cursor.to_list(length=per_page)

        # Convert to response models
        support_requests = []
        for req in requests:
            req["id"] = str(req["_id"])
            del req["_id"]
            support_requests.append(SupportRequestResponse(**req))

        return {
            "requests": support_requests,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }

    except Exception as e:
        logger.error(f"Error fetching user support requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch support requests")


async def get_all_support_requests(
    page: int = 1,
    per_page: int = 20,
    status_filter: Optional[SupportRequestStatus] = None,
    type_filter: Optional[SupportRequestType] = None,
) -> Dict:
    """
    Get all support requests (for admin use).

    Args:
        page: Page number for pagination
        per_page: Number of items per page
        status_filter: Optional status filter
        type_filter: Optional type filter

    Returns:
        Dictionary with support requests and pagination info
    """
    try:
        query = {}
        if status_filter:
            query["status"] = status_filter.value
        if type_filter:
            query["type"] = type_filter.value

        # Count total documents
        total = await support_collection.count_documents(query)

        # Calculate pagination
        skip = (page - 1) * per_page

        # Fetch documents
        cursor = (
            support_collection.find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(per_page)
        )
        requests = await cursor.to_list(length=per_page)

        # Convert to response models
        support_requests = []
        for req in requests:
            req["id"] = str(req["_id"])
            del req["_id"]
            support_requests.append(SupportRequestResponse(**req))

        return {
            "requests": support_requests,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
        }

    except Exception as e:
        logger.error(f"Error fetching all support requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch support requests")
