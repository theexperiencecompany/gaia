"""Machine-readable API error codes (mirrored in web errorCodes.ts)."""

# 401 — GAIA session missing/invalid/expired; client shows the login modal.
NOT_AUTHENTICATED = "NOT_AUTHENTICATED"

# 403 — authenticated but the integration has no active connection.
INTEGRATION_NOT_CONNECTED = "INTEGRATION_NOT_CONNECTED"
