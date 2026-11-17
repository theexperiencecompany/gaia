/**
 * Classifies a failed platform edit, so the streamer can react to WHY it failed
 * instead of treating every failure the same way.
 *
 * Every edit error used to fall into one branch that re-sent the whole reply as
 * a NEW message. When the failure was a rate limit or a transient network blip
 * — the common cases — the original bubble was still on screen, so the user got
 * the reply twice with a stale partial copy above it.
 */

import {
  GIVE_UP,
  RETRY_TIER,
  type RetryPolicy,
  type RetryVerdict,
  TRY_AGAIN,
  withRetry,
} from "../../retry/policy";
import { classifyBotFailure, isTransientBotFailure } from "./failure-reasons";
import { getHttpStatus, sanitizeErrorForLog } from "./logger";
import { sleep } from "./timeout";
import { wideLog } from "./wide-events";

/** How long to wait for a rate limit that did not say (platforms often omit it). */
const RATE_LIMIT_DEFAULT_WAIT_MS = 1_000;
/** Never wait longer than this between retries, whatever the platform asks for. */
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

/** Whether a failed call is worth another attempt, and after how long when the other side said. */
function transientVerdict(error: unknown): RetryVerdict {
  if (!isTransientBotFailure(classifyBotFailure(error))) return GIVE_UP;
  const afterMs = retryAfterMs(error);
  return afterMs === null ? TRY_AGAIN : { retry: true, afterMs };
}

/** Runs call under policy, retrying only the failures a resend can get past. */
function retryTransient<T>(
  policy: RetryPolicy,
  retrying: string,
  call: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  return withRetry(policy, call, transientVerdict, {
    sleep,
    signal,
    onRetry: (error, attempt, waitMs) =>
      wideLog.warning(retrying, {
        ...sanitizeErrorForLog(error),
        attempt,
        wait_ms: waitMs,
      }),
  });
}

/**
 * Runs one platform call under the PLATFORM_SEND tier: a transient failure waits
 * (the platform's retry_after on a rate limit) and tries again. A permanent failure
 * (chat not found, bot blocked, a rejected request), or the last transient one,
 * throws: the follow ends there and the durable re-poll delivers once the platform is back.
 */
export function retryTransientPlatformCall<T>(
  call: () => Promise<T>,
): Promise<T> {
  return retryTransient(
    RETRY_TIER.PLATFORM_SEND,
    "platform_call_retrying",
    call,
  );
}

/** Runs one call to GAIA's own API under the OWN_API tier, by the same rule; signal ends the waiting. */
export function retryOwnApiCall<T>(
  call: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  return retryTransient(
    RETRY_TIER.OWN_API,
    "own_api_call_retrying",
    call,
    signal,
  );
}
