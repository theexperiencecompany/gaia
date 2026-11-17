/**
 * The one retry rule for TypeScript clients: a bounded policy per kind of call, run by p-retry.
 *
 * Mirrors libs/shared/py/retry.py tier for tier. Nothing retries forever: past a tier's
 * last attempt the failure is thrown, and what follows is the caller's to decide.
 */
import pRetry from "p-retry";

/** How often a call is retried, and the backoff between tries (doubling from minTimeout, jittered). */
export interface RetryPolicy {
  readonly retries: number;
  readonly minTimeout: number;
  readonly maxTimeout: number;
}

/** Every retry budget, by what the call talks to. */
export const RETRY_POLICY = {
  /** A chat platform's API: send, edit, upload. */
  PLATFORM_SEND: { retries: 7, minTimeout: 500, maxTimeout: 30_000 },
  /** GAIA's own API. */
  OWN_API: { retries: 5, minTimeout: 500, maxTimeout: 10_000 },
  /** Reopening a live event stream. */
  STREAM_RECONNECT: { retries: 8, minTimeout: 500, maxTimeout: 10_000 },
} as const satisfies Record<string, RetryPolicy>;

const HTTP_REQUEST_TIMEOUT = 408;
const HTTP_TOO_MANY_REQUESTS = 429;
const HTTP_CLIENT_ERROR_MIN = 400;
const HTTP_CLIENT_ERROR_MAX = 499;

/** Whether a call that answered status may pass on a resend: a 4xx other than 408 and 429 fails the same way every time. */
export function isRetryableStatus(status: number): boolean {
  if (status === HTTP_REQUEST_TIMEOUT || status === HTTP_TOO_MANY_REQUESTS) {
    return true;
  }
  return status < HTTP_CLIENT_ERROR_MIN || status > HTTP_CLIENT_ERROR_MAX;
}

/**
 * The wait before reopening a live stream after its failures-th consecutive failure, for a
 * follow loop that withRetry cannot wrap (a stream that delivered resets its count).
 */
export function reconnectDelayMs(failures: number): number {
  const { minTimeout, maxTimeout } = RETRY_POLICY.STREAM_RECONNECT;
  return Math.min(minTimeout * 2 ** failures, maxTimeout);
}

/** What a caller tells withRetry about its call's failures. */
export interface RetryJudge {
  /** Whether this failure can pass on another attempt. */
  transient: (error: unknown) => boolean;
  /** The wait the other side named before the next attempt (a rate limit's retry_after), if any. */
  waitAsked?: (error: unknown) => number | null;
  onRetry?: (error: unknown, attempt: number) => void;
  signal?: AbortSignal;
}

/** Run call under policy, retrying only the failures judge calls transient; the last failure is thrown as it is. */
export function withRetry<T>(
  policy: RetryPolicy,
  call: () => Promise<T>,
  { transient, waitAsked, onRetry, signal }: RetryJudge,
): Promise<T> {
  return pRetry(call, {
    ...policy,
    randomize: true,
    signal,
    shouldRetry: async ({ error, attemptNumber }) => {
      if (!transient(error)) return false;
      onRetry?.(error, attemptNumber);
      const asked = waitAsked?.(error);
      if (asked) await new Promise((resolve) => setTimeout(resolve, asked));
      return true;
    },
  });
}
