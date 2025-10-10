import io
import time
import uuid
from urllib.parse import urlparse

from app.config.loggers import general_logger as logger
import cloudinary.uploader


async def upload_screenshot_to_cloudinary(
    screenshot_bytes: bytes, url: str
) -> str | None:
    """
    Upload a screenshot to Cloudinary and return the secure URL.

    Args:
        screenshot_bytes: The raw bytes of the screenshot
        url: The URL that was screenshotted (for naming purposes)

    Returns:
        str: The secure URL of the uploaded image
    """

    try:
        # Create a unique ID for the screenshot
        screenshot_id = str(uuid.uuid4())

        # Get the hostname for the public_id
        parsed_url = urlparse(url)
        hostname = parsed_url.netloc

        # Create public_id with timestamp, hostname, and UUID to ensure uniqueness
        timestamp = int(time.time())
        public_id = (
            f"screenshots/{hostname.replace('.', '_')}/{timestamp}_{screenshot_id}"
        )

        # Upload the screenshot to Cloudinary
        upload_result = cloudinary.uploader.upload(
            io.BytesIO(screenshot_bytes),
            resource_type="image",
            public_id=public_id,
            overwrite=True,
        )

        image_url = upload_result.get("secure_url")
        if not image_url:
            logger.error("Missing secure_url in Cloudinary upload response")
            return None

        logger.info(f"Screenshot uploaded successfully. URL: {image_url}")
        return image_url

    except Exception as e:
        logger.error(
            f"Failed to upload screenshot to Cloudinary: {str(e)}", exc_info=True
        )
        return None
