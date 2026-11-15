/**
 * Classifies a failed platform edit, so the streamer can react to WHY it failed
 * instead of treating every failure the same way.
 *
 * Every edit error used to fall into one branch that re-sent the whole reply as
 * a NEW message. When the failure was a rate limit or a transient network blip
 * — the common cases — the original bubble was still on screen, so the user got
 * the reply twice with a stale partial copy above it.
 */

import { getHttpStatus, sanitizeErrorForLog } from "./logger";
import { sleep } from "./timeout";
import { wideLog } from "./wide-events";

/** How long to wait for a rate limit that did not say (platforms often omit it). */
const RATE_LIMIT_DEFAULT_WAIT_MS = 1_000;
/** Never sit on a bubble longer than this, whatever the platform asks for. */
const RATE_LIMIT_MAX_WAIT_MS = 30_000;

/**
 * The message we were editing no longer exists (deleted, expired interaction,
 * or an ephemeral that cannot be edited). Telegram, Discord and Slack each
 * phrase it differently; all three mean the text has nowhere to land but a new
 * message.
 */
const MESSAGE_GONE_PATTERNS = [
  /message to edit not found/i,
  /message can'?t be edited/i,
  /message_not_found/i,
  /unknown message/i,
  /cant_update_message/i,
];

function errorText(error: unknown): string {
  if (error instanceof Error) {
    // grammY carries the Telegram reason in `description`, not `message`.
    const description = (error as { description?: unknown }).description;
    return typeof description === "string"
      ? `${error.message} ${description}`
      : error.message;
  }
  return String(error);
}

/** True when the target message is gone and the text needs a new one. */
export function isMessageGoneError(error: unknown): boolean {
  const text = errorText(error);
  return MESSAGE_GONE_PATTERNS.some((pattern) => pattern.test(text));
}

/**
 * How long to wait before retrying a rate-limited platform call (an edit, a
 * send), or `null` when the failure was not a rate limit. Reads the platform's own `retry_after`
 * (seconds) when it gave one.
 */
export function retryAfterMs(error: unknown): number | null {
  const parameters = (error as { parameters?: { retry_after?: unknown } })
    ?.parameters;
  const retryAfter = parameters?.retry_after;
  if (typeof retryAfter === "number" && retryAfter >= 0) {
    return Math.min(retryAfter * 1000, RATE_LIMIT_MAX_WAIT_MS);
  }

  const code = (error as { error_code?: unknown })?.error_code;
  const isRateLimited =
    code === 429 ||
    getHttpStatus(error) === 429 ||
    /too many requests|rate limit/i.test(errorText(error));
  return isRateLimited ? RATE_LIMIT_DEFAULT_WAIT_MS : null;
}

/** Attempts per platform call before a rate limit or server error counts as permanent. */
const PLATFORM_CALL_ATTEMPTS = 4;
const SERVER_ERROR_BACKOFF_BASE_MS = 500;
const SERVER_ERROR_BACKOFF_MAX_MS = 4_000;
const HTTP_SERVER_ERROR = 500;

/** How long to wait before retrying call attempt n, or null when its failure is permanent. */
function transientWaitMs(error: unknown, attempt: number): number | null {
  const rateLimited = retryAfterMs(error);
  if (rateLimited !== null) return rateLimited;
  const status = getHttpStatus(error);
  if (status === undefined || status < HTTP_SERVER_ERROR) return null;
  return Math.min(
    SERVER_ERROR_BACKOFF_BASE_MS * 2 ** (attempt - 1),
    SERVER_ERROR_BACKOFF_MAX_MS,
  );
}

/**
 * Runs one platform call, retrying it in place on a rate limit (after the platform's
 * retry_after) or a server error (capped backoff), a bounded number of times. A
 * permanent failure (chat not found, bot blocked) and the last attempt's failure throw.
 */
export async function retryTransientPlatformCall<T>(
  call: () => Promise<T>,
): Promise<T> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await call();
    } catch (error) {
      const waitMs = transientWaitMs(error, attempt);
      if (waitMs === null || attempt >= PLATFORM_CALL_ATTEMPTS) throw error;
      wideLog.warning("platform_call_retrying", {
        ...sanitizeErrorForLog(error),
        attempt,
        wait_ms: waitMs,
      });
      await sleep(waitMs);
    }
  }
}
