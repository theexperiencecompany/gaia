"""VFS-related constants."""

SYSTEM_USER_ID = "system"

# One path COMPONENT: an id interpolated into a JuiceFS path must not escape it.
# Lives here, not beside the mount helpers, because app.models.message_models
# constrains a field with it and reaching app.services.storage dragged that tree in.
SAFE_PATH_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
