import { INSTRUCTIONS_CONFLICT_CODE } from "@shared/constants/instructions";

// API error codes shared with the backend (apps/api/app/constants/error_codes.py).
export const API_ERROR_CODES = {
  NOT_AUTHENTICATED: "NOT_AUTHENTICATED",
  INTEGRATION_NOT_CONNECTED: "INTEGRATION_NOT_CONNECTED",
  INVALID_CREDENTIALS: "invalid_credentials",
  REGISTRATION_CLOSED: "registration_closed",
  INVITE_INVALID: "invite_invalid",
  CANNOT_REMOVE_ADMIN: "cannot_remove_admin",
  INSTRUCTIONS_CONFLICT: INSTRUCTIONS_CONFLICT_CODE,
  REFERRAL_SUBSCRIPTION_REQUIRED: "REFERRAL_SUBSCRIPTION_REQUIRED",
  REFERRALS_DISABLED: "REFERRALS_DISABLED",
} as const;

export type ApiErrorCode =
  (typeof API_ERROR_CODES)[keyof typeof API_ERROR_CODES];

/** Whether the envelope code is one the request declared as an answer it renders itself. */
export function isDeclaredAnswer(
  declared: readonly ApiErrorCode[] | undefined,
  code: string | null | undefined,
): boolean {
  const codes: readonly string[] = declared ?? [];
  return typeof code === "string" && codes.includes(code);
}
