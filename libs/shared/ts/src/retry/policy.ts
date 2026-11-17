/**
 * The one retry rule for TypeScript clients: a bounded RetryPolicy per tier, the
 * backoff it waits between attempts, and the loop that runs a call under it.
 *
 * Mirrors libs/shared/py/retry.py tier for tier. A caller never loops on its own:
 * it picks the tier its call belongs to and says which failures are worth another
 * attempt; past the tier's last attempt the failure is thrown, and what happens
 * next (a durable re-poll, a visible reconnecting state) is the caller's next state.
 */

/** How often a call is tried and how long to wait between tries. */
export interface RetryPolicy {
  readonly maxAttempts: number;
  readonly baseMs: number;
  readonly capMs: number;
  /** Wait a random share of the backoff, so clients that failed together do not retry together. */
  readonly jitter: boolean;
}

/** Every retry budget, by what the call talks to. */
export const RETRY_TIER = {
  /** A chat platform's API (send, edit, upload). */
  PLATFORM_SEND: { maxAttempts: 5, baseMs: 500, capMs: 10_000, jitter: true },
  /** GAIA's own API; past it, the work is re-polled durably, not retried in place. */
  OWN_API: { maxAttempts: 6, baseMs: 500, capMs: 10_000, jitter: true },
  /** An event stream connection; past it, the client shows it is reconnecting. */
  STREAM_RECONNECT: {
    maxAttempts: 8,
    baseMs: 500,
    capMs: 10_000,
    jitter: true,
  },
} as const satisfies Record<string, RetryPolicy>;

/** How often work OWN_API gave up on is asked for again: the durable re-poll after the tier. */
export const DURABLE_REPOLL_MS = 60_000;

/** What one failed attempt means: try again (after the server's own wait, when it named one), or stop. */
export type RetryVerdict =
  | { readonly retry: true; readonly afterMs?: number }
  | { readonly retry: false };

export const GIVE_UP: RetryVerdict = { retry: false };
export const TRY_AGAIN: RetryVerdict = { retry: true };

const HTTP_REQUEST_TIMEOUT = 408;
const HTTP_TOO_MANY_REQUESTS = 429;
const HTTP_CLIENT_ERROR_MIN = 400;
const HTTP_CLIENT_ERROR_MAX = 499;

/** Whether an HTTP status can succeed on a resend: a 4xx other than 408 and 429 fails the same way every time. */
export function isRetryableStatus(status: number): boolean {
  if (status === HTTP_REQUEST_TIMEOUT || status === HTTP_TOO_MANY_REQUESTS)
    return true;
  return status < HTTP_CLIENT_ERROR_MIN || status > HTTP_CLIENT_ERROR_MAX;
}

/** The wait before attempt `attempt + 1` (attempt counts from 1): doubling from the base, capped, jittered. */
export function backoffMs(
  policy: RetryPolicy,
  attempt: number,
  random: () => number = Math.random,
): number {
  const full = Math.min(policy.baseMs * 2 ** (attempt - 1), policy.capMs);
  return policy.jitter ? full / 2 + (random() * full) / 2 : full;
}

/** Hooks a caller gives withRetry: how to wait, what to note before each retry, and when to stop early. */
export interface RetryOptions {
  /** Waits ms; resolves early when signal aborts. */
  sleep: (ms: number, signal?: AbortSignal) => Promise<void>;
  onRetry?: (error: unknown, attempt: number, waitMs: number) => void;
  random?: () => number;
  /** Aborted: the last failure is rethrown instead of trying again. */
  signal?: AbortSignal;
}

/**
 * Run call under policy: a failure judge() says is worth another attempt waits (the
 * server's own wait when it named one, else the backoff) and tries again. A failure
 * judged final, the one after the tier's last attempt, or one when signal aborted
 * is rethrown as it is.
 */
export async function withRetry<T>(
  policy: RetryPolicy,
  call: () => Promise<T>,
  judge: (error: unknown) => RetryVerdict,
  { sleep, onRetry, random, signal }: RetryOptions,
): Promise<T> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await call();
    } catch (error) {
      const verdict = judge(error);
      if (!verdict.retry || attempt >= policy.maxAttempts) throw error;
      const waitMs = verdict.afterMs ?? backoffMs(policy, attempt, random);
      onRetry?.(error, attempt, waitMs);
      await sleep(waitMs, signal);
      if (signal?.aborted) throw error;
    }
  }
}
