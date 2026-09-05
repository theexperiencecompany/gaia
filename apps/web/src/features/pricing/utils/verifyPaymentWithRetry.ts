import type { PaymentVerificationResponse } from "../api/pricingApi";

export type VerifyPaymentFn = () => Promise<PaymentVerificationResponse>;

export type VerifyRetryOptions = {
  /** Total verification calls, including the first. */
  attempts?: number;
  /** Delay before the first retry. */
  baseDelayMs?: number;
  /** Extra delay added per subsequent retry. */
  delayStepMs?: number;
};

const DEFAULT_ATTEMPTS = 8;
const DEFAULT_BASE_DELAY_MS = 2_500;
const DEFAULT_DELAY_STEP_MS = 1_500;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Verifies a payment, tolerating the webhook-vs-redirect race: Dodo's
 * redirect can land the user on the result page before the
 * `subscription.active` webhook has been processed, so a single
 * "not completed" response is not a failure — it just means the record
 * has not landed yet. Retries with growing delays (staying well under
 * the endpoint's 20/minute rate limit) until the payment confirms or
 * the attempts run out.
 *
 * - Stops and returns as soon as a verify reports the payment completed.
 * - Retries both "not completed" results and thrown errors (network
 *   flakes included); whichever happened on the final attempt wins:
 *   the last not-completed result is returned, the last error is thrown.
 */
export async function verifyPaymentWithRetry(
  verify: VerifyPaymentFn,
  {
    attempts = DEFAULT_ATTEMPTS,
    baseDelayMs = DEFAULT_BASE_DELAY_MS,
    delayStepMs = DEFAULT_DELAY_STEP_MS,
  }: VerifyRetryOptions = {},
): Promise<PaymentVerificationResponse> {
  let lastResult: PaymentVerificationResponse | null = null;
  let lastError: unknown = null;

  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      const result = await verify();
      if (result.payment_completed) {
        return result;
      }
      lastResult = result;
      lastError = null;
    } catch (error) {
      lastError = error;
      lastResult = null;
    }

    if (attempt < attempts) {
      await sleep(baseDelayMs + delayStepMs * (attempt - 1));
    }
  }

  if (lastError !== null) {
    throw lastError;
  }
  return lastResult as PaymentVerificationResponse;
}
