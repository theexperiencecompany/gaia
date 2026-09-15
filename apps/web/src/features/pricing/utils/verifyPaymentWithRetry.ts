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
 * Verifies a payment, tolerating the webhook-vs-redirect race: a redirect can
 * land the user before the webhook lands, so one "not completed" isn't a
 * failure. Shares `CHECKOUT_CONFIRM_TOTAL_BUDGET_MS` with the in-app wizard —
 * two budgets for one wait once told a paying user "not completed" 4 minutes early.
 *
 * Stops on the first completed result; otherwise retries both "not completed"
 * and thrown errors, and the final attempt's outcome wins either way.
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
