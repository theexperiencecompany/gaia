import type { PaymentVerificationResponse } from "../api/pricingApi";
import { CHECKOUT_CONFIRM_TOTAL_BUDGET_MS } from "../constants";

export type VerifyPaymentFn = () => Promise<PaymentVerificationResponse>;

export type VerifyRetryOptions = {
  /** Gap before each retry; one entry per retry after the first call. */
  delays?: number[];
};

const BASE_DELAY_MS = 2_500;
const DELAY_STEP_MS = 1_500;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * The gaps between verification calls: 2.5s, then 4s, then 5.5s, each a step
 * longer than the last so a webhook that lands early is seen quickly and a
 * slow one is not hammered (the endpoint allows 20/minute). The final gap is
 * clipped so the gaps together fill exactly `budgetMs` — the schedule is the
 * budget, which is what stops the result page from giving up on a payment the
 * checkout wizard is still waiting on.
 */
export function retryDelays(budgetMs: number): number[] {
  const delays: number[] = [];
  let spent = 0;
  while (spent < budgetMs) {
    const delay = Math.min(
      BASE_DELAY_MS + DELAY_STEP_MS * delays.length,
      budgetMs - spent,
    );
    delays.push(delay);
    spent += delay;
  }
  return delays;
}

/**
 * Verifies a payment, tolerating the webhook-vs-redirect race: Dodo's
 * redirect can land the user on the result page before the
 * `subscription.active` webhook has been processed, so a single
 * "not completed" response is not a failure — it just means the record
 * has not landed yet.
 *
 * The wait is the same `CHECKOUT_CONFIRM_TOTAL_BUDGET_MS` the in-app checkout
 * wizard spends on the identical race. Two budgets for one wait is how the
 * result page came to tell a paying user "Payment not completed" four minutes
 * before the wizard would have stopped believing in them.
 *
 * - Stops and returns as soon as a verify reports the payment completed.
 * - Retries both "not completed" results and thrown errors (network
 *   flakes included); whichever happened on the final attempt wins:
 *   the last not-completed result is returned, the last error is thrown.
 */
export async function verifyPaymentWithRetry(
  verify: VerifyPaymentFn,
  {
    delays = retryDelays(CHECKOUT_CONFIRM_TOTAL_BUDGET_MS),
  }: VerifyRetryOptions = {},
): Promise<PaymentVerificationResponse> {
  let lastResult: PaymentVerificationResponse | null = null;
  let lastError: unknown = null;

  for (let attempt = 0; attempt <= delays.length; attempt++) {
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

    if (attempt < delays.length) {
      await sleep(delays[attempt]);
    }
  }

  if (lastError !== null) {
    throw lastError;
  }
  return lastResult as PaymentVerificationResponse;
}
