import os
from typing import Optional

import cloudinary
import cloudinary.exceptions
import cloudinary.uploader
from fastapi import HTTPException

from app.config.loggers import app_logger as logger


def upload_file_to_cloudinary(
    public_id: str,
    file_data: Optional[bytes] = None,
    file_path: Optional[str] = None,
) -> str:
    """
    Uploads a file to Cloudinary and returns the URL.

    Args:
        file_data (bytes, optional): The file data to upload.
        file_path (str, optional): The path to the file to upload.
        public_id (str): The public ID for the uploaded file.

    Returns:
        str: The URL of the uploaded file.

    Raises:
        HTTPException: If the upload fails or invalid parameters are provided.
    """
    # Validate input parameters
    if not file_data and not file_path:
        logger.error("Either file_data or file_path must be provided")
        raise HTTPException(
            status_code=400, detail="Either file_data or file_path must be provided"
        )

    if file_data and file_path:
        logger.error("Cannot provide both file_data and file_path")
        raise HTTPException(
            status_code=400,
            detail="Cannot provide both file_data and file_path - choose one",
        )

    if not public_id:
        logger.error("public_id is required")
        raise HTTPException(status_code=400, detail="public_id is required")

    # Validate file path exists if provided
    if file_path and not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    try:
        # Determine the source for upload
        upload_source = file_data if file_data else file_path

        upload_result = cloudinary.uploader.upload(
            upload_source,
            resource_type="auto",
            public_id=public_id,
            overwrite=True,
        )

        file_url = upload_result.get("secure_url")
        if not file_url:
            logger.error("Missing secure_url in Cloudinary upload response")
            raise HTTPException(
                status_code=500, detail="Invalid response from file upload service"
            )

        source_type = "file_data" if file_data else "file_path"
        logger.info(f"File uploaded successfully from {source_type}. URL: {file_url}")
        return file_url

    except cloudinary.exceptions.Error as e:
        logger.error(f"Cloudinary upload failed: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to upload file to Cloudinary"
        )
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred during file upload"
        )
