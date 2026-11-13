/**
 * Why a bot operation failed, as one closed code set shared by every platform,
 * so `| json | reason="account_not_linked"` finds the same failure on each.
 */
import { BOT_STREAM_ERROR } from "../api/chat-stream";
import { getApiErrorCode, getHttpStatus } from "./logger";
import { wideLog } from "./wide-events";

/** API error codes the bots act on; mirrors apps/api/app/constants/error_codes.py. */
const API_ERROR_CODE = {
  NOT_AUTHENTICATED: "NOT_AUTHENTICATED",
  BOT_ACCOUNT_NOT_LINKED: "BOT_ACCOUNT_NOT_LINKED",
  BOT_API_KEY_INVALID: "BOT_API_KEY_INVALID",
} as const;

export const BOT_FAILURE_REASON = {
  ACCOUNT_NOT_LINKED: "account_not_linked",
  BOT_API_KEY_INVALID: "bot_api_key_invalid",
  UNAUTHORIZED: "unauthorized",
  PLAN_REQUIRED: "plan_required",
  NOT_FOUND: "not_found",
  RATE_LIMITED: "rate_limited",
  DESTINATION_NOT_FOUND: "destination_not_found",
  DESTINATION_BLOCKED: "destination_blocked",
  CLIENT_ERROR: "client_error",
  SERVER_ERROR: "server_error",
  TIMEOUT: "timeout",
  BACKEND_UNREACHABLE: "backend_unreachable",
  /** An outbound envelope dead-lettered before any send: unparseable, invalid or empty. */
  ENVELOPE_REJECTED: "envelope_rejected",
  /** An outbound file over the platform's size cap; the user got a note instead. */
  FILE_TOO_LARGE: "file_too_large",
  UNKNOWN: "unknown",
} as const;

export type BotFailureReason =
  (typeof BOT_FAILURE_REASON)[keyof typeof BOT_FAILURE_REASON];

/**
 * The failures a retry can get past: the platform or network, not the request.
 * Everything else (a chat that is gone, a blocked bot, a rejected request) fails
 * the same way on every attempt.
 */
const TRANSIENT_FAILURE_REASONS: ReadonlySet<BotFailureReason> = new Set([
  BOT_FAILURE_REASON.SERVER_ERROR,
  BOT_FAILURE_REASON.TIMEOUT,
  BOT_FAILURE_REASON.RATE_LIMITED,
  BOT_FAILURE_REASON.BACKEND_UNREACHABLE,
]);

/** Whether a failure with this reason may succeed if the same request is sent again. */
export function isTransientBotFailure(reason: BotFailureReason): boolean {
  return TRANSIENT_FAILURE_REASONS.has(reason);
}

const NOT_LINKED_CODES: ReadonlySet<string> = new Set([
  API_ERROR_CODE.NOT_AUTHENTICATED,
  API_ERROR_CODE.BOT_ACCOUNT_NOT_LINKED,
]);

// Telegram, Discord and Slack each word "that chat/user does not exist" and
// "that user will not take messages from the bot" differently.
const DESTINATION_NOT_FOUND_PATTERNS = [
  /chat not found/i,
  /user not found/i,
  /unknown (channel|user)/i,
  /channel_not_found|user_not_found|is_archived/i,
];
const DESTINATION_BLOCKED_PATTERNS = [
  /bot was blocked by the user/i,
  /user is deactivated/i,
  /bot can'?t initiate conversation/i,
  /cannot send messages to this user/i,
  /not_in_channel/i,
];
const BACKEND_UNREACHABLE_PATTERNS = [
  /ECONNREFUSED|ETIMEDOUT|ECONNRESET|socket hang up/,
  /^aborted$/,
  /No response received|Connection lost before receiving a response/,
  /Connection interrupted/,
];
const TIMEOUT_PATTERN = /timed out|timeout/i;

const HTTP_BAD_REQUEST = 400;
const HTTP_UNAUTHORIZED = 401;
const HTTP_PAYMENT_REQUIRED = 402;
const HTTP_FORBIDDEN = 403;
const HTTP_NOT_FOUND = 404;
const HTTP_TOO_MANY_REQUESTS = 429;
const HTTP_SERVER_ERROR = 500;

function errorText(error: unknown): string {
  if (!(error instanceof Error)) return String(error ?? "");
  // grammY carries Telegram's reason in `description`, not `message`.
  const description = (error as { description?: unknown }).description;
  return typeof description === "string"
    ? `${error.message} ${description}`
    : error.message;
}

function reasonFromStatus(
  status: number,
  error: unknown,
): BotFailureReason | undefined {
  if (status === HTTP_UNAUTHORIZED) {
    const code = getApiErrorCode(error);
    if (code === API_ERROR_CODE.BOT_API_KEY_INVALID) {
      return BOT_FAILURE_REASON.BOT_API_KEY_INVALID;
    }
    return code !== undefined && NOT_LINKED_CODES.has(code)
      ? BOT_FAILURE_REASON.ACCOUNT_NOT_LINKED
      : BOT_FAILURE_REASON.UNAUTHORIZED;
  }
  if (status === HTTP_PAYMENT_REQUIRED) return BOT_FAILURE_REASON.PLAN_REQUIRED;
  if (status === HTTP_FORBIDDEN) return BOT_FAILURE_REASON.UNAUTHORIZED;
  if (status === HTTP_NOT_FOUND) return BOT_FAILURE_REASON.NOT_FOUND;
  if (status === HTTP_TOO_MANY_REQUESTS) return BOT_FAILURE_REASON.RATE_LIMITED;
  if (status >= HTTP_SERVER_ERROR) return BOT_FAILURE_REASON.SERVER_ERROR;
  if (status >= HTTP_BAD_REQUEST) return BOT_FAILURE_REASON.CLIENT_ERROR;
  return undefined;
}

/** Classifies a failed GAIA API call, stream or platform send into one reason. */
export function classifyBotFailure(error: unknown): BotFailureReason {
  const text = errorText(error);
  if (text === BOT_STREAM_ERROR.notAuthenticated) {
    return BOT_FAILURE_REASON.ACCOUNT_NOT_LINKED;
  }
  if (text === BOT_STREAM_ERROR.planRequired) {
    return BOT_FAILURE_REASON.PLAN_REQUIRED;
  }
  if (DESTINATION_BLOCKED_PATTERNS.some((p) => p.test(text))) {
    return BOT_FAILURE_REASON.DESTINATION_BLOCKED;
  }
  if (DESTINATION_NOT_FOUND_PATTERNS.some((p) => p.test(text))) {
    return BOT_FAILURE_REASON.DESTINATION_NOT_FOUND;
  }
  const status = getHttpStatus(error);
  const fromStatus =
    status === undefined ? undefined : reasonFromStatus(status, error);
  if (fromStatus) return fromStatus;
  if (BACKEND_UNREACHABLE_PATTERNS.some((p) => p.test(text))) {
    return BOT_FAILURE_REASON.BACKEND_UNREACHABLE;
  }
  if (TIMEOUT_PATTERN.test(text)) return BOT_FAILURE_REASON.TIMEOUT;
  return BOT_FAILURE_REASON.UNKNOWN;
}

/**
 * Records a failure the caller caught and answered: an errors[] entry named
 * `message` (with the error's type, HTTP status and API code), and the active
 * event marked failed with the classified reason. Returns that reason.
 */
export function recordBotFailure(
  message: string,
  error: unknown,
  fields?: Record<string, unknown>,
): BotFailureReason {
  const reason = classifyBotFailure(error);
  wideLog.fail(reason, {
    http_status: getHttpStatus(error),
    error_code: getApiErrorCode(error),
  });
  wideLog.error(message, { ...fields, reason }, error);
  return reason;
}
