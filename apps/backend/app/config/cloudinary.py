import cloudinary
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider


@lazy_provider(
    name="cloudinary",
    required_keys=[
        settings.CLOUDINARY_CLOUD_NAME,
        settings.CLOUDINARY_API_KEY,
        settings.CLOUDINARY_API_SECRET,
    ],
    auto_initialize=True,
    is_global_context=True,
    strategy=MissingKeyStrategy.WARN,
    warning_message="Cloudinary configuration is missing or incomplete. Cloudinary features will be disabled.",
)
def init_cloudinary():
    """
    Initialize and configure the Cloudinary service.

    This function sets up the Cloudinary configuration using the provided
    environment variables for cloud name, API key, and API secret. If any
    of these values are missing, it logs an error and raises an HTTPException.

        dict: A dictionary containing the Cloudinary configuration values:
            - cloud_name (str): The Cloudinary cloud name.
            - api_key (str): The Cloudinary API key.
            - api_secret (str): The Cloudinary API secret.

    Returns:
        dict: Cloudinary configuration.
    """
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
    )
