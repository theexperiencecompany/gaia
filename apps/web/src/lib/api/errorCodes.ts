import { INSTRUCTIONS_CONFLICT_CODE } from "@shared/constants/instructions";

// API error codes shared with the backend (apps/api/app/constants/error_codes.py).
export const API_ERROR_CODES = {
  NOT_AUTHENTICATED: "NOT_AUTHENTICATED",
  INTEGRATION_NOT_CONNECTED: "INTEGRATION_NOT_CONNECTED",
  INSTRUCTIONS_CONFLICT: INSTRUCTIONS_CONFLICT_CODE,
} as const;
