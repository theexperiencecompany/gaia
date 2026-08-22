// API error codes shared with the backend (apps/api/app/constants/error_codes.py).
export const API_ERROR_CODES = {
  NOT_AUTHENTICATED: "NOT_AUTHENTICATED",
  INTEGRATION_NOT_CONNECTED: "INTEGRATION_NOT_CONNECTED",
  INVALID_CREDENTIALS: "invalid_credentials",
  REGISTRATION_CLOSED: "registration_closed",
} as const;
